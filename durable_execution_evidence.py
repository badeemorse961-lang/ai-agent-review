from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from durable_execution_state import (
    ARTIFACT_STATES,
    CHECKPOINT_STATES,
    DELIVERY_STATES,
    LEASE_STATES,
    RECOVERY_OPERATION_STATES,
    VALIDATION_STATES,
    DurableExecutionState,
    IntegrityError,
    InvalidTransitionError,
    LineageError,
    StateConflictError,
    WorkspaceEvidence,
    utc_now,
)

_CHECKPOINT_TRANSITIONS = {"CREATED": {"TRUSTED", "INVALID"}, "TRUSTED": set(), "INVALID": set()}
_ARTIFACT_TRANSITIONS = {
    "ARTIFACT_UNVALIDATED": {"ARTIFACT_VALIDATED", "ARTIFACT_INCOMPLETE", "ARTIFACT_INVALID", "ARTIFACT_AMBIGUOUS"},
    "ARTIFACT_VALIDATED": {"ARTIFACT_INCOMPLETE", "ARTIFACT_INVALID"},
    "ARTIFACT_INCOMPLETE": {"ARTIFACT_UNVALIDATED", "ARTIFACT_INVALID", "ARTIFACT_AMBIGUOUS"},
    "ARTIFACT_INVALID": {"ARTIFACT_UNVALIDATED"},
    "ARTIFACT_AMBIGUOUS": {"ARTIFACT_UNVALIDATED"},
}
_VALIDATION_TRANSITIONS = {
    "PENDING": {"PASSED", "FAILED", "REQUIRES_REVALIDATION"},
    "PASSED": {"REQUIRES_REVALIDATION"},
    "FAILED": {"REQUIRES_REVALIDATION"},
    "REQUIRES_REVALIDATION": {"PASSED", "FAILED"},
}
_LEASE_TRANSITIONS = {
    "ACTIVE": {"RELEASED", "STALE", "AMBIGUOUS"},
    "RELEASED": set(),
    "STALE": {"RECLAIMED", "AMBIGUOUS"},
    "RECLAIMED": set(),
    "AMBIGUOUS": {"RECLAIMED"},
}
_RECOVERY_OPERATION_TRANSITIONS = {
    "PLANNED": {"STARTED", "FAILED"},
    "STARTED": {"EFFECT_OBSERVED", "UNKNOWN", "FAILED"},
    "EFFECT_OBSERVED": {"VERIFIED", "UNKNOWN", "FAILED"},
    "VERIFIED": {"COMMITTED", "FAILED"},
    "COMMITTED": set(),
    "UNKNOWN": {"VERIFIED", "RECOVERY_REQUIRED", "SAFE_STOP"},
    "FAILED": set(),
    "RECOVERY_REQUIRED": set(),
    "SAFE_STOP": set(),
}
_DELIVERY_TRANSITIONS = {
    "DELIVERY_PENDING": {"DELIVERY_STARTED"},
    "DELIVERY_STARTED": {"DELIVERY_INTERRUPTED", "DELIVERY_COMMITTED", "DELIVERY_RECOVERY_REQUIRED"},
    "DELIVERY_INTERRUPTED": {"DELIVERY_STARTED", "DELIVERY_RECOVERY_REQUIRED", "DELIVERY_COMMITTED"},
    "DELIVERY_RECOVERY_REQUIRED": {"DELIVERY_STARTED", "DELIVERY_COMMITTED"},
    "DELIVERY_COMMITTED": {"DELIVERY_VERIFIED"},
    "DELIVERY_VERIFIED": set(),
}


def evidence_digest(evidence: WorkspaceEvidence) -> str:
    payload = {
        "project_id": evidence.project_id,
        "run_id": evidence.run_id,
        "phase_id": evidence.phase_id,
        "task_id": evidence.task_id,
        "attempt_id": evidence.attempt_id,
        "relative_path": evidence.relative_path,
        "change_kind": evidence.change_kind,
        "expected_before_identity": evidence.expected_before_identity,
        "observed_before_identity": evidence.observed_before_identity,
        "expected_after_identity": evidence.expected_after_identity,
        "observed_after_identity": evidence.observed_after_identity,
        "observed_state": evidence.observed_state,
        "checkpoint_id": evidence.checkpoint_id,
        "artifact_id": evidence.artifact_id,
        "evidence_created_at": evidence.evidence_created_at,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CheckpointRecord:
    checkpoint_id: str
    project_id: str
    run_id: str
    phase_id: str
    task_id: str
    attempt_id: str
    sequence: int
    checkpoint_kind: str
    workspace_evidence_identity: str
    workspace_evidence_hash: str
    created_at: str
    status: str


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    project_id: str
    run_id: str
    phase_id: str
    task_id: str
    attempt_id: str
    reference: str
    identity: str
    checksum: Optional[str]
    state: str
    created_at: str


@dataclass(frozen=True)
class ValidationRecord:
    validation_id: str
    project_id: str
    run_id: str
    phase_id: str
    task_id: str
    attempt_id: str
    artifact_id: Optional[str]
    checkpoint_sequence: int
    state: str
    validated_at: Optional[str]
    evidence_hash: Optional[str]


@dataclass(frozen=True)
class LeaseBindingRecord:
    lease_id: str
    project_id: str
    run_id: str
    phase_id: str
    task_id: str
    attempt_id: str
    worker_id: Optional[str]
    bound_at: str
    released_at: Optional[str]
    state: str


@dataclass(frozen=True)
class RecoveryOperationRecord:
    operation_id: str
    idempotency_key: str
    project_id: str
    run_id: str
    phase_id: Optional[str]
    task_id: Optional[str]
    attempt_id: Optional[str]
    operation_kind: str
    state: str
    started_at: Optional[str]
    completed_at: Optional[str]
    effect_reference: Optional[str]
    effect_hash: Optional[str]


class EvidenceLayer:
    """M2 lifecycle API over the single DurableExecutionState authority."""

    def __init__(self, state: DurableExecutionState) -> None:
        self.state = state

    def record_workspace_evidence(self, evidence: WorkspaceEvidence) -> int:
        if evidence.change_kind not in {"CREATED", "MODIFIED", "DELETED"}:
            raise ValueError("Unsupported workspace change_kind")
        if evidence.observed_state not in {"PRESENT_COMPLETE", "PRESENT_PARTIAL", "ABSENT", "MISMATCH", "AMBIGUOUS"}:
            raise ValueError("Unsupported workspace observed_state")
        with self.state._transaction() as conn:
            self.state._require_attempt(conn, evidence.project_id, evidence.run_id, evidence.phase_id, evidence.task_id, evidence.attempt_id)
            if evidence.checkpoint_id is not None:
                checkpoint = self.state._require_checkpoint(conn, evidence.checkpoint_id)
                self._require_exact_lineage(checkpoint, evidence.project_id, evidence.run_id, evidence.phase_id, evidence.task_id, evidence.attempt_id)
            if evidence.artifact_id is not None:
                artifact = self.state._require_artifact(conn, evidence.artifact_id)
                self._require_exact_lineage(artifact, evidence.project_id, evidence.run_id, evidence.phase_id, evidence.task_id, evidence.attempt_id)
            run = self.state._require_run(conn, evidence.project_id, evidence.run_id)
            next_sequence = int(run["sequence"]) + 1
            cursor = conn.execute("INSERT INTO workspace_evidence(project_id, run_id, phase_id, task_id, attempt_id, relative_path, change_kind, expected_before_identity, observed_before_identity, expected_after_identity, observed_after_identity, observed_state, checkpoint_id, artifact_id, evidence_created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (evidence.project_id, evidence.run_id, evidence.phase_id, evidence.task_id, evidence.attempt_id, evidence.relative_path, evidence.change_kind, evidence.expected_before_identity, evidence.observed_before_identity, evidence.expected_after_identity, evidence.observed_after_identity, evidence.observed_state, evidence.checkpoint_id, evidence.artifact_id, evidence.evidence_created_at))
            evidence_id = int(cursor.lastrowid)
            self.state._append_event_tx(conn, project_id=evidence.project_id, run_id=evidence.run_id, sequence=next_sequence, event_type="WORKSPACE_EVIDENCE_RECORDED", entity_type="workspace_evidence", entity_id=str(evidence_id), payload={"phase_id": evidence.phase_id, "task_id": evidence.task_id, "attempt_id": evidence.attempt_id, "relative_path": evidence.relative_path, "change_kind": evidence.change_kind, "observed_state": evidence.observed_state, "checkpoint_id": evidence.checkpoint_id, "artifact_id": evidence.artifact_id})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, evidence.project_id, evidence.run_id))
            return evidence_id

    def create_checkpoint(self, *, project_id: str, run_id: str, phase_id: str, task_id: str, attempt_id: str, sequence: int, checkpoint_kind: str, workspace_evidence_identity: str, workspace_evidence_hash: str, checkpoint_id: str) -> CheckpointRecord:
        if sequence <= 0 or not workspace_evidence_identity or not workspace_evidence_hash:
            raise IntegrityError("Checkpoint requires positive sequence and workspace evidence identity/hash")
        with self.state._transaction() as conn:
            self.state._require_attempt(conn, project_id, run_id, phase_id, task_id, attempt_id)
            evidence = conn.execute("SELECT * FROM workspace_evidence WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=? ORDER BY evidence_id DESC", (project_id, run_id, phase_id, task_id, attempt_id)).fetchall()
            matching = [row for row in evidence if (row["observed_after_identity"] or row["expected_after_identity"]) == workspace_evidence_identity and self._evidence_row_digest(row) == workspace_evidence_hash]
            if not matching:
                raise IntegrityError("Checkpoint requires matching workspace evidence identity and hash")
            latest_sequence = int(conn.execute("SELECT COALESCE(MAX(sequence),0) FROM checkpoints WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (project_id, run_id, phase_id, task_id, attempt_id)).fetchone()[0])
            if sequence <= latest_sequence:
                raise StateConflictError("Checkpoint sequence must increase monotonically")
            existing = conn.execute("SELECT * FROM checkpoints WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
            if existing is not None:
                if any(existing[key] != value for key, value in {"project_id": project_id, "run_id": run_id, "phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id, "sequence": sequence, "checkpoint_kind": checkpoint_kind, "workspace_evidence_identity": workspace_evidence_identity, "workspace_evidence_hash": workspace_evidence_hash}.items()):
                    raise LineageError("Checkpoint identity already maps to different evidence")
                return self._checkpoint_record(existing)
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute("INSERT INTO checkpoints(checkpoint_id, project_id, run_id, phase_id, task_id, attempt_id, sequence, checkpoint_kind, workspace_evidence_identity, workspace_evidence_hash, created_at, status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (checkpoint_id, project_id, run_id, phase_id, task_id, attempt_id, sequence, checkpoint_kind, workspace_evidence_identity, workspace_evidence_hash, utc_now(), "CREATED"))
            conn.execute("UPDATE attempts SET checkpoint_sequence=? WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (sequence, project_id, run_id, phase_id, task_id, attempt_id))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type="CHECKPOINT_CREATED", entity_type="checkpoint", entity_id=checkpoint_id, payload={"phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id, "checkpoint_sequence": sequence, "checkpoint_kind": checkpoint_kind})
            conn.execute("UPDATE runs SET sequence=?, last_checkpoint_seq=? WHERE project_id=? AND run_id=?", (next_sequence, sequence, project_id, run_id))
            return self._checkpoint_record(conn.execute("SELECT * FROM checkpoints WHERE checkpoint_id=?", (checkpoint_id,)).fetchone())

    def transition_checkpoint(self, *, project_id: str, run_id: str, checkpoint_id: str, new_status: str) -> CheckpointRecord:
        if new_status not in CHECKPOINT_STATES:
            raise InvalidTransitionError(f"Unknown checkpoint state: {new_status}")
        with self.state._transaction() as conn:
            row = self.state._require_checkpoint(conn, checkpoint_id)
            self._require_run_lineage(row, project_id, run_id)
            current = str(row["status"])
            if new_status == current or new_status not in _CHECKPOINT_TRANSITIONS[current]:
                raise InvalidTransitionError(f"Forbidden checkpoint transition: {current} -> {new_status}")
            evidence = conn.execute("SELECT * FROM workspace_evidence WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (project_id, run_id, row["phase_id"], row["task_id"], row["attempt_id"])).fetchall()
            if not any((item["observed_after_identity"] or item["expected_after_identity"]) == row["workspace_evidence_identity"] and self._evidence_row_digest(item) == row["workspace_evidence_hash"] for item in evidence):
                raise IntegrityError("Checkpoint cannot be trusted without matching workspace evidence")
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute("UPDATE checkpoints SET status=? WHERE checkpoint_id=?", (new_status, checkpoint_id))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type=f"CHECKPOINT_{new_status}", entity_type="checkpoint", entity_id=checkpoint_id, payload={"status": new_status, "checkpoint_sequence": int(row["sequence"] )})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            return self._checkpoint_record(conn.execute("SELECT * FROM checkpoints WHERE checkpoint_id=?", (checkpoint_id,)).fetchone())

    def register_artifact(self, *, project_id: str, run_id: str, phase_id: str, task_id: str, attempt_id: str, artifact_id: str, reference: str, identity: str, checksum: Optional[str] = None) -> ArtifactRecord:
        if not reference or not identity:
            raise IntegrityError("Artifact reference and identity are required")
        with self.state._transaction() as conn:
            self.state._require_attempt(conn, project_id, run_id, phase_id, task_id, attempt_id)
            existing = conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            if existing is not None:
                if any(existing[key] != value for key, value in {"project_id": project_id, "run_id": run_id, "phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id, "reference": reference, "identity": identity, "checksum": checksum}.items()):
                    raise LineageError("Artifact identity already maps to different lineage")
                return self._artifact_record(existing)
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute("INSERT INTO artifacts(artifact_id, project_id, run_id, phase_id, task_id, attempt_id, reference, identity, checksum, state, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (artifact_id, project_id, run_id, phase_id, task_id, attempt_id, reference, identity, checksum, "ARTIFACT_UNVALIDATED", utc_now()))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type="ARTIFACT_REGISTERED", entity_type="artifact", entity_id=artifact_id, payload={"phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id, "state": "ARTIFACT_UNVALIDATED"})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            return self._artifact_record(conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone())

    def validate_artifact(self, *, project_id: str, run_id: str, artifact_id: str, observed_identity: str, observed_checksum: Optional[str]) -> ArtifactRecord:
        with self.state._transaction() as conn:
            row = self.state._require_artifact(conn, artifact_id)
            self._require_run_lineage(row, project_id, run_id)
            if observed_identity != row["identity"]:
                raise IntegrityError("Artifact identity mismatch")
            if row["checksum"] is not None and observed_checksum != row["checksum"]:
                raise IntegrityError("Artifact checksum mismatch")
            if row["state"] == "ARTIFACT_VALIDATED":
                return self._artifact_record(row)
            if row["state"] != "ARTIFACT_UNVALIDATED":
                raise InvalidTransitionError(f"Artifact cannot be validated from {row['state']}")
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute("UPDATE artifacts SET state='ARTIFACT_VALIDATED' WHERE artifact_id=?", (artifact_id,))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type="ARTIFACT_VALIDATED", entity_type="artifact", entity_id=artifact_id, payload={"identity": observed_identity, "checksum": observed_checksum})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            return self._artifact_record(conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone())

    def transition_artifact(self, *, project_id: str, run_id: str, artifact_id: str, new_state: str) -> ArtifactRecord:
        if new_state not in ARTIFACT_STATES:
            raise InvalidTransitionError(f"Unknown artifact state: {new_state}")
        with self.state._transaction() as conn:
            row = self.state._require_artifact(conn, artifact_id)
            self._require_run_lineage(row, project_id, run_id)
            current = str(row["state"])
            if new_state == current or new_state not in _ARTIFACT_TRANSITIONS[current]:
                raise InvalidTransitionError(f"Forbidden artifact transition: {current} -> {new_state}")
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute("UPDATE artifacts SET state=? WHERE artifact_id=?", (new_state, artifact_id))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type=f"ARTIFACT_{new_state.removeprefix('ARTIFACT_')}", entity_type="artifact", entity_id=artifact_id, payload={"state": new_state})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            return self._artifact_record(conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone())

    def create_validation(self, *, project_id: str, run_id: str, phase_id: str, task_id: str, attempt_id: str, checkpoint_sequence: int, validation_id: str, artifact_id: Optional[str] = None) -> ValidationRecord:
        with self.state._transaction() as conn:
            self.state._require_attempt(conn, project_id, run_id, phase_id, task_id, attempt_id)
            checkpoint = conn.execute("SELECT * FROM checkpoints WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=? AND sequence=?", (project_id, run_id, phase_id, task_id, attempt_id, checkpoint_sequence)).fetchone()
            if checkpoint is None:
                raise LineageError("Validation references missing checkpoint")
            if artifact_id is not None:
                artifact = self.state._require_artifact(conn, artifact_id)
                self._require_exact_lineage(artifact, project_id, run_id, phase_id, task_id, attempt_id)
            existing = conn.execute("SELECT * FROM validations WHERE validation_id=?", (validation_id,)).fetchone()
            if existing is not None:
                self._require_exact_lineage(existing, project_id, run_id, phase_id, task_id, attempt_id)
                return self._validation_record(existing)
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute("INSERT INTO validations(validation_id, project_id, run_id, phase_id, task_id, attempt_id, artifact_id, checkpoint_sequence, state, validated_at, evidence_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (validation_id, project_id, run_id, phase_id, task_id, attempt_id, artifact_id, checkpoint_sequence, "PENDING", None, None))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type="VALIDATION_CREATED", entity_type="validation", entity_id=validation_id, payload={"phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id, "artifact_id": artifact_id, "checkpoint_sequence": checkpoint_sequence, "state": "PENDING"})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            return self._validation_record(conn.execute("SELECT * FROM validations WHERE validation_id=?", (validation_id,)).fetchone())

    def transition_validation(self, *, project_id: str, run_id: str, validation_id: str, new_state: str, evidence_hash: Optional[str] = None) -> ValidationRecord:
        if new_state not in VALIDATION_STATES:
            raise InvalidTransitionError(f"Unknown validation state: {new_state}")
        with self.state._transaction() as conn:
            row = conn.execute("SELECT * FROM validations WHERE validation_id=?", (validation_id,)).fetchone()
            if row is None:
                raise LineageError(f"Unknown validation: {validation_id}")
            self._require_run_lineage(row, project_id, run_id)
            current = str(row["state"])
            if new_state == current or new_state not in _VALIDATION_TRANSITIONS[current]:
                raise InvalidTransitionError(f"Forbidden validation transition: {current} -> {new_state}")
            checkpoint = conn.execute("SELECT * FROM checkpoints WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=? AND sequence=?", (project_id, run_id, row["phase_id"], row["task_id"], row["attempt_id"], row["checkpoint_sequence"])).fetchone()
            if checkpoint is None:
                raise LineageError("Validation checkpoint is missing")
            if new_state == "PASSED":
                if checkpoint["status"] != "TRUSTED":
                    raise IntegrityError("Validation cannot pass against untrusted checkpoint")
                if evidence_hash != checkpoint["workspace_evidence_hash"]:
                    raise IntegrityError("Validation evidence hash mismatch")
                if row["artifact_id"] is not None and self.state._require_artifact(conn, row["artifact_id"])["state"] != "ARTIFACT_VALIDATED":
                    raise IntegrityError("Validation cannot pass an unvalidated artifact")
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute("UPDATE validations SET state=?, validated_at=?, evidence_hash=COALESCE(?, evidence_hash) WHERE validation_id=?", (new_state, utc_now() if new_state == "PASSED" else row["validated_at"], evidence_hash, validation_id))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type=f"VALIDATION_{new_state}", entity_type="validation", entity_id=validation_id, payload={"state": new_state, "checkpoint_sequence": int(row["checkpoint_sequence"]), "artifact_id": row["artifact_id"]})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            return self._validation_record(conn.execute("SELECT * FROM validations WHERE validation_id=?", (validation_id,)).fetchone())

    def bind_lease(self, *, project_id: str, run_id: str, phase_id: str, task_id: str, attempt_id: str, lease_id: str, worker_id: Optional[str]) -> LeaseBindingRecord:
        with self.state._transaction() as conn:
            self.state._require_attempt(conn, project_id, run_id, phase_id, task_id, attempt_id)
            existing_active = conn.execute("SELECT * FROM lease_bindings WHERE project_id=? AND run_id=? AND task_id=? AND state='ACTIVE'", (project_id, run_id, task_id)).fetchone()
            if existing_active is not None and existing_active["lease_id"] != lease_id:
                raise StateConflictError("An active durable lease already owns this task")
            existing = conn.execute("SELECT * FROM lease_bindings WHERE lease_id=?", (lease_id,)).fetchone()
            if existing is not None:
                self._require_run_lineage(existing, project_id, run_id)
                return self._lease_record(existing)
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute("INSERT INTO lease_bindings(lease_id, project_id, run_id, phase_id, task_id, attempt_id, worker_id, bound_at, released_at, state) VALUES(?,?,?,?,?,?,?,?,?,?)", (lease_id, project_id, run_id, phase_id, task_id, attempt_id, worker_id, utc_now(), None, "ACTIVE"))
            conn.execute("UPDATE attempts SET lease_id=? WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (lease_id, project_id, run_id, phase_id, task_id, attempt_id))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type="LEASE_BOUND", entity_type="lease", entity_id=lease_id, payload={"phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id, "worker_id": worker_id, "state": "ACTIVE"})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            return self._lease_record(conn.execute("SELECT * FROM lease_bindings WHERE lease_id=?", (lease_id,)).fetchone())

    def transition_lease(self, *, project_id: str, run_id: str, lease_id: str, new_state: str) -> LeaseBindingRecord:
        if new_state not in LEASE_STATES:
            raise InvalidTransitionError(f"Unknown lease state: {new_state}")
        with self.state._transaction() as conn:
            row = conn.execute("SELECT * FROM lease_bindings WHERE lease_id=?", (lease_id,)).fetchone()
            if row is None:
                raise LineageError(f"Unknown lease: {lease_id}")
            self._require_run_lineage(row, project_id, run_id)
            current = str(row["state"])
            if new_state == current or new_state not in _LEASE_TRANSITIONS[current]:
                raise InvalidTransitionError(f"Forbidden lease transition: {current} -> {new_state}")
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            released_at = utc_now() if new_state in {"RELEASED", "RECLAIMED", "AMBIGUOUS"} else row["released_at"]
            conn.execute("UPDATE lease_bindings SET state=?, released_at=? WHERE lease_id=?", (new_state, released_at, lease_id))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type=f"LEASE_{new_state}", entity_type="lease", entity_id=lease_id, payload={"task_id": row["task_id"], "attempt_id": row["attempt_id"], "state": new_state})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            return self._lease_record(conn.execute("SELECT * FROM lease_bindings WHERE lease_id=?", (lease_id,)).fetchone())

    def create_recovery_operation(self, *, project_id: str, run_id: str, operation_kind: str, idempotency_key: str, phase_id: Optional[str] = None, task_id: Optional[str] = None, attempt_id: Optional[str] = None) -> RecoveryOperationRecord:
        if not operation_kind or not idempotency_key:
            raise ValueError("operation_kind and idempotency_key are required")
        with self.state._transaction() as conn:
            self.state._require_run(conn, project_id, run_id)
            if phase_id is not None:
                self.state._require_phase(conn, project_id, run_id, phase_id)
            if task_id is not None:
                if phase_id is None:
                    raise LineageError("task binding requires phase_id")
                self.state._require_task(conn, project_id, run_id, phase_id, task_id)
            if attempt_id is not None:
                if phase_id is None or task_id is None:
                    raise LineageError("attempt binding requires phase_id and task_id")
                self.state._require_attempt(conn, project_id, run_id, phase_id, task_id, attempt_id)
            existing = conn.execute("SELECT * FROM recovery_operations WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing is not None:
                if any(existing[key] != value for key, value in {"project_id": project_id, "run_id": run_id, "phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id, "operation_kind": operation_kind}.items()):
                    raise LineageError("Idempotency key is already bound to different recovery context")
                return self._recovery_record(existing)
            operation_id = __import__("uuid").uuid4().hex
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute("INSERT INTO recovery_operations(operation_id, idempotency_key, project_id, run_id, phase_id, task_id, attempt_id, operation_kind, state) VALUES(?,?,?,?,?,?,?,?,?)", (operation_id, idempotency_key, project_id, run_id, phase_id, task_id, attempt_id, operation_kind, "PLANNED"))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type="RECOVERY_OPERATION_PLANNED", entity_type="recovery_operation", entity_id=operation_id, payload={"operation_kind": operation_kind, "idempotency_key": idempotency_key, "phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            return self._recovery_record(conn.execute("SELECT * FROM recovery_operations WHERE operation_id=?", (operation_id,)).fetchone())

    def transition_recovery_operation(self, *, project_id: str, run_id: str, operation_id: str, new_state: str, effect_reference: Optional[str] = None, effect_hash: Optional[str] = None) -> RecoveryOperationRecord:
        if new_state not in RECOVERY_OPERATION_STATES:
            raise InvalidTransitionError(f"Unknown recovery operation state: {new_state}")
        with self.state._transaction() as conn:
            row = conn.execute("SELECT * FROM recovery_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                raise LineageError(f"Unknown recovery operation: {operation_id}")
            self._require_run_lineage(row, project_id, run_id)
            current = str(row["state"])
            if new_state == current or new_state not in _RECOVERY_OPERATION_TRANSITIONS[current]:
                raise InvalidTransitionError(f"Forbidden recovery operation transition: {current} -> {new_state}")
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            now = utc_now()
            conn.execute("UPDATE recovery_operations SET state=?, started_at=COALESCE(started_at, ?), completed_at=?, effect_reference=COALESCE(?, effect_reference), effect_hash=COALESCE(?, effect_hash) WHERE operation_id=?", (new_state, now if new_state == "STARTED" else row["started_at"], now if new_state in {"VERIFIED", "COMMITTED", "FAILED"} else row["completed_at"], effect_reference, effect_hash, operation_id))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type=f"RECOVERY_OPERATION_{new_state}", entity_type="recovery_operation", entity_id=operation_id, payload={"operation_kind": row["operation_kind"], "state": new_state, "effect_reference": effect_reference, "effect_hash": effect_hash})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            return self._recovery_record(conn.execute("SELECT * FROM recovery_operations WHERE operation_id=?", (operation_id,)).fetchone())

    def set_delivery_state(self, *, project_id: str, run_id: str, new_state: str) -> Any:
        if new_state not in DELIVERY_STATES:
            raise InvalidTransitionError(f"Unknown delivery state: {new_state}")
        with self.state._transaction() as conn:
            run = self.state._require_run(conn, project_id, run_id)
            current = str(run["delivery_state"])
            if new_state == current or new_state not in _DELIVERY_TRANSITIONS[current]:
                raise InvalidTransitionError(f"Forbidden delivery transition: {current} -> {new_state}")
            next_sequence = int(run["sequence"]) + 1
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type=new_state, entity_type="delivery", entity_id=run_id, payload={"delivery_state": new_state})
            conn.execute("UPDATE runs SET delivery_state=?, sequence=? WHERE project_id=? AND run_id=?", (new_state, next_sequence, project_id, run_id))
        return self.state.get_run(run_id, project_id=project_id)

    @staticmethod
    def _require_run_lineage(row: Mapping[str, Any], project_id: str, run_id: str) -> None:
        if row["project_id"] != project_id or row["run_id"] != run_id:
            raise LineageError("Cross-project/run reference rejected")

    @staticmethod
    def _require_exact_lineage(row: Mapping[str, Any], project_id: str, run_id: str, phase_id: str, task_id: str, attempt_id: str) -> None:
        if (row["project_id"], row["run_id"], row["phase_id"], row["task_id"], row["attempt_id"]) != (project_id, run_id, phase_id, task_id, attempt_id):
            raise LineageError("Cross-execution lineage reference rejected")

    @staticmethod
    def _evidence_row_digest(row: Mapping[str, Any]) -> str:
        payload = {"project_id": row["project_id"], "run_id": row["run_id"], "phase_id": row["phase_id"], "task_id": row["task_id"], "attempt_id": row["attempt_id"], "relative_path": row["relative_path"], "change_kind": row["change_kind"], "expected_before_identity": row["expected_before_identity"], "observed_before_identity": row["observed_before_identity"], "expected_after_identity": row["expected_after_identity"], "observed_after_identity": row["observed_after_identity"], "observed_state": row["observed_state"], "checkpoint_id": row["checkpoint_id"], "artifact_id": row["artifact_id"], "evidence_created_at": row["evidence_created_at"]}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @staticmethod
    def _checkpoint_record(row: Mapping[str, Any]) -> CheckpointRecord:
        return CheckpointRecord(str(row["checkpoint_id"]), str(row["project_id"]), str(row["run_id"]), str(row["phase_id"]), str(row["task_id"]), str(row["attempt_id"]), int(row["sequence"]), str(row["checkpoint_kind"]), str(row["workspace_evidence_identity"]), str(row["workspace_evidence_hash"]), str(row["created_at"]), str(row["status"]))

    @staticmethod
    def _artifact_record(row: Mapping[str, Any]) -> ArtifactRecord:
        return ArtifactRecord(str(row["artifact_id"]), str(row["project_id"]), str(row["run_id"]), str(row["phase_id"]), str(row["task_id"]), str(row["attempt_id"]), str(row["reference"]), str(row["identity"]), row["checksum"], str(row["state"]), str(row["created_at"]))

    @staticmethod
    def _validation_record(row: Mapping[str, Any]) -> ValidationRecord:
        return ValidationRecord(str(row["validation_id"]), str(row["project_id"]), str(row["run_id"]), str(row["phase_id"]), str(row["task_id"]), str(row["attempt_id"]), row["artifact_id"], int(row["checkpoint_sequence"]), str(row["state"]), row["validated_at"], row["evidence_hash"])

    @staticmethod
    def _lease_record(row: Mapping[str, Any]) -> LeaseBindingRecord:
        return LeaseBindingRecord(str(row["lease_id"]), str(row["project_id"]), str(row["run_id"]), str(row["phase_id"]), str(row["task_id"]), str(row["attempt_id"]), row["worker_id"], str(row["bound_at"]), row["released_at"], str(row["state"]))

    @staticmethod
    def _recovery_record(row: Mapping[str, Any]) -> RecoveryOperationRecord:
        return RecoveryOperationRecord(str(row["operation_id"]), str(row["idempotency_key"]), str(row["project_id"]), str(row["run_id"]), row["phase_id"], row["task_id"], row["attempt_id"], str(row["operation_kind"]), str(row["state"]), row["started_at"], row["completed_at"], row["effect_reference"], row["effect_hash"])


__all__ = [
    "ArtifactRecord",
    "CheckpointRecord",
    "EvidenceLayer",
    "LeaseBindingRecord",
    "RecoveryOperationRecord",
    "ValidationRecord",
    "evidence_digest",
]
