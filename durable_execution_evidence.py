from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from durable_execution_state import (
    ARTIFACT_STATES,
    ATTEMPT_STATES,
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
    _canonical_json,
    _hash_text,
    utc_now,
)


_CHECKPOINT_TRANSITIONS = {
    "CREATED": {"TRUSTED", "INVALID"},
    "TRUSTED": set(),
    "INVALID": set(),
}
_ARTIFACT_TRANSITIONS = {
    "ARTIFACT_DISCOVERED": {"ARTIFACT_UNVALIDATED", "ARTIFACT_INCOMPLETE", "ARTIFACT_INVALID", "ARTIFACT_AMBIGUOUS"},
    "ARTIFACT_UNVALIDATED": {"ARTIFACT_VALIDATED", "ARTIFACT_INCOMPLETE", "ARTIFACT_INVALID", "ARTIFACT_AMBIGUOUS"},
    "ARTIFACT_VALIDATED": set(),
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


@dataclass(frozen=True)
class CheckpointRecord:
    checkpoint_id: str
    project_id: str
    run_id: str
    phase_id: str
    task_id: Optional[str]
    attempt_id: Optional[str]
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
    """M2 evidence/lifecycle API over the single DurableExecutionState authority."""

    def __init__(self, state: DurableExecutionState) -> None:
        self.state = state

    def create_checkpoint(
        self,
        *,
        project_id: str,
        run_id: str,
        phase_id: str,
        task_id: Optional[str],
        attempt_id: Optional[str],
        sequence: int,
        checkpoint_kind: str,
        workspace_evidence_identity: str,
        workspace_evidence_hash: str,
        checkpoint_id: str,
        status: str = "CREATED",
    ) -> CheckpointRecord:
        self._validate_checkpoint_lineage(project_id, run_id, phase_id, task_id, attempt_id)
        if status not in CHECKPOINT_STATES:
            raise InvalidTransitionError(f"Unknown checkpoint state: {status}")
        if not workspace_evidence_identity or not workspace_evidence_hash:
            raise IntegrityError("Checkpoint requires workspace evidence identity and hash")
        run = self.state.get_run(run_id, project_id=project_id)
        if sequence > run.sequence:
            raise StateConflictError(
                f"Checkpoint sequence {sequence} cannot exceed current Run sequence {run.sequence}"
            )
        with self.state._transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM checkpoints WHERE checkpoint_id=?",
                (checkpoint_id,),
            ).fetchone()
            if existing is not None:
                if any(
                    existing[key] != value
                    for key, value in {
                        "project_id": project_id,
                        "run_id": run_id,
                        "phase_id": phase_id,
                        "task_id": task_id,
                        "attempt_id": attempt_id,
                        "sequence": sequence,
                        "checkpoint_kind": checkpoint_kind,
                        "workspace_evidence_identity": workspace_evidence_identity,
                        "workspace_evidence_hash": workspace_evidence_hash,
                    }.items()
                ):
                    raise LineageError("Checkpoint identity is already bound to different evidence")
                return self._checkpoint_record(existing)
            conn.execute(
                "INSERT INTO checkpoints(checkpoint_id, project_id, run_id, phase_id, task_id, attempt_id, sequence, checkpoint_kind, workspace_evidence_identity, workspace_evidence_hash, created_at, status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    checkpoint_id,
                    project_id,
                    run_id,
                    phase_id,
                    task_id,
                    attempt_id,
                    sequence,
                    checkpoint_kind,
                    workspace_evidence_identity,
                    workspace_evidence_hash,
                    utc_now(),
                    status,
                ),
            )
            self.state._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=run.sequence + 1,
                event_type="CHECKPOINT_CREATED",
                entity_type="checkpoint",
                entity_id=checkpoint_id,
                payload={"phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id, "checkpoint_sequence": sequence, "status": status},
            )
            conn.execute(
                "UPDATE runs SET sequence=?, last_checkpoint_seq=? WHERE project_id=? AND run_id=?",
                (run.sequence + 1, sequence, project_id, run_id),
            )
            row = conn.execute("SELECT * FROM checkpoints WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
        return self._checkpoint_record(row)

    def transition_checkpoint(self, *, project_id: str, run_id: str, checkpoint_id: str, new_status: str) -> CheckpointRecord:
        if new_status not in CHECKPOINT_STATES:
            raise InvalidTransitionError(f"Unknown checkpoint state: {new_status}")
        with self.state._transaction() as conn:
            row = self.state._require_checkpoint(conn, checkpoint_id)
            self._require_row_lineage(row, project_id, run_id)
            current = str(row["status"])
            if new_status == current or new_status not in _CHECKPOINT_TRANSITIONS[current]:
                raise InvalidTransitionError(f"Forbidden checkpoint transition: {current} -> {new_status}")
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            self.state._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=next_sequence,
                event_type=f"CHECKPOINT_{new_status}",
                entity_type="checkpoint",
                entity_id=checkpoint_id,
                payload={"status": new_status, "checkpoint_sequence": int(row["sequence"])},
            )
            conn.execute(
                "UPDATE checkpoints SET status=? WHERE checkpoint_id=?",
                (new_status, checkpoint_id),
            )
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            updated = conn.execute("SELECT * FROM checkpoints WHERE checkpoint_id=?", (checkpoint_id,)).fetchone()
        return self._checkpoint_record(updated)

    def register_artifact(
        self,
        *,
        project_id: str,
        run_id: str,
        phase_id: str,
        task_id: str,
        attempt_id: str,
        artifact_id: str,
        reference: str,
        identity: str,
        checksum: Optional[str] = None,
        state: str = "ARTIFACT_UNVALIDATED",
    ) -> ArtifactRecord:
        self.state._require_attempt(self.state._connection, project_id, run_id, phase_id, task_id, attempt_id)
        if not reference or not identity:
            raise IntegrityError("Artifact reference and identity are required")
        if state not in ARTIFACT_STATES:
            raise InvalidTransitionError(f"Unknown artifact state: {state}")
        with self.state._transaction() as conn:
            self.state._require_attempt(conn, project_id, run_id, phase_id, task_id, attempt_id)
            existing = conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
            if existing is not None:
                if any(existing[key] != value for key, value in {
                    "project_id": project_id, "run_id": run_id, "phase_id": phase_id,
                    "task_id": task_id, "attempt_id": attempt_id, "reference": reference,
                    "identity": identity, "checksum": checksum,
                }.items()):
                    raise LineageError("Artifact identity is already bound to different lineage/evidence")
                return self._artifact_record(existing)
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute(
                "INSERT INTO artifacts(artifact_id, project_id, run_id, phase_id, task_id, attempt_id, reference, identity, checksum, state, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (artifact_id, project_id, run_id, phase_id, task_id, attempt_id, reference, identity, checksum, state, utc_now()),
            )
            self.state._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=next_sequence,
                event_type="ARTIFACT_REGISTERED",
                entity_type="artifact",
                entity_id=artifact_id,
                payload={"phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id, "state": state, "identity": identity, "checksum": checksum},
            )
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            row = conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        return self._artifact_record(row)

    def transition_artifact(self, *, project_id: str, run_id: str, artifact_id: str, new_state: str) -> ArtifactRecord:
        if new_state not in ARTIFACT_STATES:
            raise InvalidTransitionError(f"Unknown artifact state: {new_state}")
        with self.state._transaction() as conn:
            row = self.state._require_artifact(conn, artifact_id)
            self._require_row_lineage(row, project_id, run_id)
            current = str(row["state"])
            if new_state == current or new_state not in _ARTIFACT_TRANSITIONS[current]:
                raise InvalidTransitionError(f"Forbidden artifact transition: {current} -> {new_state}")
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            self.state._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=next_sequence,
                event_type=f"ARTIFACT_{new_state.removeprefix('ARTIFACT_')}",
                entity_type="artifact",
                entity_id=artifact_id,
                payload={"state": new_state},
            )
            conn.execute("UPDATE artifacts SET state=? WHERE artifact_id=?", (new_state, artifact_id))
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            updated = conn.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone()
        return self._artifact_record(updated)

    def create_validation(
        self,
        *,
        project_id: str,
        run_id: str,
        phase_id: str,
        task_id: str,
        attempt_id: str,
        checkpoint_sequence: int,
        validation_id: str,
        artifact_id: Optional[str] = None,
        state: str = "PENDING",
        evidence_hash: Optional[str] = None,
    ) -> ValidationRecord:
        if state not in VALIDATION_STATES:
            raise InvalidTransitionError(f"Unknown validation state: {state}")
        with self.state._transaction() as conn:
            self.state._require_attempt(conn, project_id, run_id, phase_id, task_id, attempt_id)
            if artifact_id is not None:
                artifact = self.state._require_artifact(conn, artifact_id)
                self._require_exact_lineage(artifact, project_id, run_id, phase_id, task_id, attempt_id)
            checkpoint = conn.execute(
                "SELECT * FROM checkpoints WHERE project_id=? AND run_id=? AND sequence=? ORDER BY created_at DESC LIMIT 1",
                (project_id, run_id, checkpoint_sequence),
            ).fetchone()
            if checkpoint is None:
                raise LineageError("Validation references unknown checkpoint sequence")
            self._require_row_lineage(checkpoint, project_id, run_id)
            if checkpoint["phase_id"] != phase_id or checkpoint["task_id"] != task_id or checkpoint["attempt_id"] != attempt_id:
                raise LineageError("Validation checkpoint does not match attempt lineage")
            if artifact_id is not None and checkpoint["status"] != "TRUSTED":
                raise IntegrityError("Validation cannot trust an artifact against an untrusted checkpoint")
            if state == "PASSED" and (artifact_id is not None):
                artifact = self.state._require_artifact(conn, artifact_id)
                if artifact["state"] != "ARTIFACT_VALIDATED":
                    raise IntegrityError("PASSED validation requires an ARTIFACT_VALIDATED artifact")
            with self.state._transaction() as nested:
                pass
        with self.state._transaction() as conn:
            existing = conn.execute("SELECT * FROM validations WHERE validation_id=?", (validation_id,)).fetchone()
            if existing is not None:
                return self._validation_record(existing)
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute(
                "INSERT INTO validations(validation_id, project_id, run_id, phase_id, task_id, attempt_id, artifact_id, checkpoint_sequence, state, validated_at, evidence_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (validation_id, project_id, run_id, phase_id, task_id, attempt_id, artifact_id, checkpoint_sequence, state, utc_now() if state == "PASSED" else None, evidence_hash),
            )
            self.state._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=next_sequence,
                event_type="VALIDATION_CREATED",
                entity_type="validation",
                entity_id=validation_id,
                payload={"phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id, "artifact_id": artifact_id, "checkpoint_sequence": checkpoint_sequence, "state": state},
            )
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            row = conn.execute("SELECT * FROM validations WHERE validation_id=?", (validation_id,)).fetchone()
        return self._validation_record(row)

    def transition_validation(self, *, project_id: str, run_id: str, validation_id: str, new_state: str, evidence_hash: Optional[str] = None) -> ValidationRecord:
        if new_state not in VALIDATION_STATES:
            raise InvalidTransitionError(f"Unknown validation state: {new_state}")
        with self.state._transaction() as conn:
            row = conn.execute("SELECT * FROM validations WHERE validation_id=?", (validation_id,)).fetchone()
            if row is None:
                raise LineageError(f"Unknown validation: {validation_id}")
            self._require_row_lineage(row, project_id, run_id)
            current = str(row["state"])
            if new_state == current or new_state not in _VALIDATION_TRANSITIONS[current]:
                raise InvalidTransitionError(f"Forbidden validation transition: {current} -> {new_state}")
            self.state._require_attempt(conn, project_id, run_id, row["phase_id"], row["task_id"], row["attempt_id"])
            checkpoint = conn.execute(
                "SELECT * FROM checkpoints WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=? AND sequence=?",
                (project_id, run_id, row["phase_id"], row["task_id"], row["attempt_id"], row["checkpoint_sequence"]),
            ).fetchone()
            if checkpoint is None:
                raise LineageError("Validation checkpoint is missing")
            if new_state == "PASSED":
                if checkpoint["status"] != "TRUSTED":
                    raise IntegrityError("Validation cannot pass against an untrusted checkpoint")
                if row["artifact_id"] is not None:
                    artifact = self.state._require_artifact(conn, row["artifact_id"])
                    if artifact["state"] != "ARTIFACT_VALIDATED":
                        raise IntegrityError("Validation cannot pass an unvalidated artifact")
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            self.state._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=next_sequence,
                event_type=f"VALIDATION_{new_state}",
                entity_type="validation",
                entity_id=validation_id,
                payload={"state": new_state, "checkpoint_sequence": int(row["checkpoint_sequence"]), "artifact_id": row["artifact_id"]},
            )
            conn.execute(
                "UPDATE validations SET state=?, validated_at=?, evidence_hash=COALESCE(?, evidence_hash) WHERE validation_id=?",
                (new_state, utc_now() if new_state == "PASSED" else row["validated_at"], evidence_hash, validation_id),
            )
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            updated = conn.execute("SELECT * FROM validations WHERE validation_id=?", (validation_id,)).fetchone()
        return self._validation_record(updated)

    def bind_lease(
        self,
        *,
        project_id: str,
        run_id: str,
        phase_id: str,
        task_id: str,
        attempt_id: str,
        lease_id: str,
        worker_id: Optional[str],
    ) -> LeaseBindingRecord:
        with self.state._transaction() as conn:
            self.state._require_attempt(conn, project_id, run_id, phase_id, task_id, attempt_id)
            duplicate = conn.execute(
                "SELECT * FROM lease_bindings WHERE project_id=? AND run_id=? AND task_id=? AND state='ACTIVE'",
                (project_id, run_id, task_id),
            ).fetchone()
            if duplicate is not None and duplicate["lease_id"] != lease_id:
                raise StateConflictError("An active durable lease already owns this task")
            existing = conn.execute("SELECT * FROM lease_bindings WHERE lease_id=?", (lease_id,)).fetchone()
            if existing is not None:
                self._require_row_lineage(existing, project_id, run_id)
                return self._lease_record(existing)
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute(
                "INSERT INTO lease_bindings(lease_id, project_id, run_id, phase_id, task_id, attempt_id, worker_id, bound_at, released_at, state) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (lease_id, project_id, run_id, phase_id, task_id, attempt_id, worker_id, utc_now(), None, "ACTIVE"),
            )
            self.state._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=next_sequence,
                event_type="LEASE_BOUND",
                entity_type="lease",
                entity_id=lease_id,
                payload={"phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id, "worker_id": worker_id, "state": "ACTIVE"},
            )
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            row = conn.execute("SELECT * FROM lease_bindings WHERE lease_id=?", (lease_id,)).fetchone()
        return self._lease_record(row)

    def transition_lease(self, *, project_id: str, run_id: str, lease_id: str, new_state: str) -> LeaseBindingRecord:
        if new_state not in LEASE_STATES:
            raise InvalidTransitionError(f"Unknown lease state: {new_state}")
        with self.state._transaction() as conn:
            row = conn.execute("SELECT * FROM lease_bindings WHERE lease_id=?", (lease_id,)).fetchone()
            if row is None:
                raise LineageError(f"Unknown lease: {lease_id}")
            self._require_row_lineage(row, project_id, run_id)
            current = str(row["state"])
            if new_state == current or new_state not in _LEASE_TRANSITIONS[current]:
                raise InvalidTransitionError(f"Forbidden lease transition: {current} -> {new_state}")
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            released_at = utc_now() if new_state in {"RELEASED", "RECLAIMED", "AMBIGUOUS"} else row["released_at"]
            self.state._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=next_sequence,
                event_type=f"LEASE_{new_state}",
                entity_type="lease",
                entity_id=lease_id,
                payload={"task_id": row["task_id"], "attempt_id": row["attempt_id"], "state": new_state},
            )
            conn.execute("UPDATE lease_bindings SET state=?, released_at=? WHERE lease_id=?", (new_state, released_at, lease_id))
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            updated = conn.execute("SELECT * FROM lease_bindings WHERE lease_id=?", (lease_id,)).fetchone()
        return self._lease_record(updated)

    def transition_recovery_operation(
        self,
        *,
        project_id: str,
        run_id: str,
        operation_id: str,
        new_state: str,
        effect_reference: Optional[str] = None,
        effect_hash: Optional[str] = None,
    ) -> RecoveryOperationRecord:
        if new_state not in RECOVERY_OPERATION_STATES and new_state not in {"RECOVERY_REQUIRED", "SAFE_STOP"}:
            raise InvalidTransitionError(f"Unknown recovery operation state: {new_state}")
        with self.state._transaction() as conn:
            row = conn.execute("SELECT * FROM recovery_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if row is None:
                raise LineageError(f"Unknown recovery operation: {operation_id}")
            self._require_row_lineage(row, project_id, run_id)
            current = str(row["state"])
            allowed = _RECOVERY_OPERATION_TRANSITIONS.get(current, set())
            if new_state == current or new_state not in allowed:
                raise InvalidTransitionError(f"Forbidden recovery operation transition: {current} -> {new_state}")
            run = self.state._require_run(conn, project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            now = utc_now()
            conn.execute(
                "UPDATE recovery_operations SET state=?, started_at=COALESCE(started_at, ?), completed_at=?, effect_reference=COALESCE(?, effect_reference), effect_hash=COALESCE(?, effect_hash) WHERE operation_id=?",
                (new_state, now if new_state == "STARTED" else row["started_at"], now if new_state in {"VERIFIED", "COMMITTED", "FAILED", "RECOVERY_REQUIRED", "SAFE_STOP"} else row["completed_at"], effect_reference, effect_hash, operation_id),
            )
            self.state._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=next_sequence,
                event_type=f"RECOVERY_OPERATION_{new_state}",
                entity_type="recovery_operation",
                entity_id=operation_id,
                payload={"idempotency_key": row["idempotency_key"], "operation_kind": row["operation_kind"], "state": new_state, "effect_reference": effect_reference, "effect_hash": effect_hash},
            )
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            updated = conn.execute("SELECT * FROM recovery_operations WHERE operation_id=?", (operation_id,)).fetchone()
        return self._recovery_record(updated)

    def set_delivery_state(self, *, project_id: str, run_id: str, new_state: str) -> Any:
        if new_state not in DELIVERY_STATES:
            raise InvalidTransitionError(f"Unknown delivery state: {new_state}")
        allowed = {
            "DELIVERY_PENDING": {"DELIVERY_STARTED"},
            "DELIVERY_STARTED": {"DELIVERY_INTERRUPTED", "DELIVERY_COMMITTED", "DELIVERY_RECOVERY_REQUIRED"},
            "DELIVERY_INTERRUPTED": {"DELIVERY_STARTED", "DELIVERY_RECOVERY_REQUIRED", "DELIVERY_COMMITTED"},
            "DELIVERY_RECOVERY_REQUIRED": {"DELIVERY_STARTED", "DELIVERY_COMMITTED"},
            "DELIVERY_COMMITTED": {"DELIVERY_VERIFIED"},
            "DELIVERY_VERIFIED": set(),
        }
        with self.state._transaction() as conn:
            run = self.state._require_run(conn, project_id, run_id)
            current = str(run["delivery_state"])
            if new_state == current or new_state not in allowed[current]:
                raise InvalidTransitionError(f"Forbidden delivery transition: {current} -> {new_state}")
            next_sequence = int(run["sequence"]) + 1
            self.state._append_event_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                sequence=next_sequence,
                event_type=f"{new_state}",
                entity_type="delivery",
                entity_id=run_id,
                payload={"delivery_state": new_state},
            )
            conn.execute("UPDATE runs SET delivery_state=?, sequence=? WHERE project_id=? AND run_id=?", (new_state, next_sequence, project_id, run_id))
        return self.state.get_run(run_id, project_id=project_id)

    def record_workspace_evidence(self, evidence: WorkspaceEvidence) -> int:
        with self.state._transaction() as conn:
            evidence_id = self.state.record_workspace_evidence.__func__(self.state, evidence) if False else None
            self.state._require_attempt(conn, evidence.project_id, evidence.run_id, evidence.phase_id, evidence.task_id, evidence.attempt_id)
            if evidence.checkpoint_id is not None:
                checkpoint = self.state._require_checkpoint(conn, evidence.checkpoint_id)
                self._require_exact_lineage(checkpoint, evidence.project_id, evidence.run_id, evidence.phase_id, evidence.task_id, evidence.attempt_id)
            if evidence.artifact_id is not None:
                artifact = self.state._require_artifact(conn, evidence.artifact_id)
                self._require_exact_lineage(artifact, evidence.project_id, evidence.run_id, evidence.phase_id, evidence.task_id, evidence.attempt_id)
                if artifact["state"] == "ARTIFACT_INVALID" and evidence.observed_state == "PRESENT_COMPLETE":
                    raise IntegrityError("Invalid artifact cannot be recorded as complete workspace evidence")
            cursor = conn.execute(
                "INSERT INTO workspace_evidence(project_id, run_id, phase_id, task_id, attempt_id, relative_path, change_kind, expected_before_identity, observed_before_identity, expected_after_identity, observed_after_identity, observed_state, checkpoint_id, artifact_id, evidence_created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (evidence.project_id, evidence.run_id, evidence.phase_id, evidence.task_id, evidence.attempt_id, evidence.relative_path, evidence.change_kind, evidence.expected_before_identity, evidence.observed_before_identity, evidence.expected_after_identity, evidence.observed_after_identity, evidence.observed_state, evidence.checkpoint_id, evidence.artifact_id, evidence.evidence_created_at),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def _require_row_lineage(row: Mapping[str, Any], project_id: str, run_id: str) -> None:
        if row["project_id"] != project_id or row["run_id"] != run_id:
            raise LineageError("Cross-project/run reference rejected")

    @staticmethod
    def _require_exact_lineage(row: Mapping[str, Any], project_id: str, run_id: str, phase_id: str, task_id: str, attempt_id: str) -> None:
        values = (row["project_id"], row["run_id"], row["phase_id"], row["task_id"], row["attempt_id"])
        if values != (project_id, run_id, phase_id, task_id, attempt_id):
            raise LineageError("Cross-execution lineage reference rejected")

    def _validate_checkpoint_lineage(self, project_id: str, run_id: str, phase_id: str, task_id: Optional[str], attempt_id: Optional[str]) -> None:
        self.state._require_phase(self.state._connection, project_id, run_id, phase_id)
        if task_id is None and attempt_id is not None:
            raise LineageError("Checkpoint attempt binding requires task_id")
        if task_id is not None:
            self.state._require_task(self.state._connection, project_id, run_id, phase_id, task_id)
        if attempt_id is not None:
            self.state._require_attempt(self.state._connection, project_id, run_id, phase_id, task_id or "", attempt_id)

    @staticmethod
    def _checkpoint_record(row: Mapping[str, Any]) -> CheckpointRecord:
        return CheckpointRecord(
            checkpoint_id=str(row["checkpoint_id"]), project_id=str(row["project_id"]), run_id=str(row["run_id"]),
            phase_id=str(row["phase_id"]), task_id=row["task_id"], attempt_id=row["attempt_id"], sequence=int(row["sequence"]),
            checkpoint_kind=str(row["checkpoint_kind"]), workspace_evidence_identity=str(row["workspace_evidence_identity"]),
            workspace_evidence_hash=str(row["workspace_evidence_hash"]), created_at=str(row["created_at"]), status=str(row["status"]),
        )

    @staticmethod
    def _artifact_record(row: Mapping[str, Any]) -> ArtifactRecord:
        return ArtifactRecord(
            artifact_id=str(row["artifact_id"]), project_id=str(row["project_id"]), run_id=str(row["run_id"]), phase_id=str(row["phase_id"]),
            task_id=str(row["task_id"]), attempt_id=str(row["attempt_id"]), reference=str(row["reference"]), identity=str(row["identity"]),
            checksum=row["checksum"], state=str(row["state"]), created_at=str(row["created_at"]),
        )

    @staticmethod
    def _validation_record(row: Mapping[str, Any]) -> ValidationRecord:
        return ValidationRecord(
            validation_id=str(row["validation_id"]), project_id=str(row["project_id"]), run_id=str(row["run_id"]), phase_id=str(row["phase_id"]),
            task_id=str(row["task_id"]), attempt_id=str(row["attempt_id"]), artifact_id=row["artifact_id"], checkpoint_sequence=int(row["checkpoint_sequence"]),
            state=str(row["state"]), validated_at=row["validated_at"], evidence_hash=row["evidence_hash"],
        )

    @staticmethod
    def _lease_record(row: Mapping[str, Any]) -> LeaseBindingRecord:
        return LeaseBindingRecord(
            lease_id=str(row["lease_id"]), project_id=str(row["project_id"]), run_id=str(row["run_id"]), phase_id=str(row["phase_id"]),
            task_id=str(row["task_id"]), attempt_id=str(row["attempt_id"]), worker_id=row["worker_id"], bound_at=str(row["bound_at"]),
            released_at=row["released_at"], state=str(row["state"]),
        )

    @staticmethod
    def _recovery_record(row: Mapping[str, Any]) -> RecoveryOperationRecord:
        return RecoveryOperationRecord(
            operation_id=str(row["operation_id"]), idempotency_key=str(row["idempotency_key"]), project_id=str(row["project_id"]),
            run_id=str(row["run_id"]), phase_id=row["phase_id"], task_id=row["task_id"], attempt_id=row["attempt_id"],
            operation_kind=str(row["operation_kind"]), state=str(row["state"]), started_at=row["started_at"], completed_at=row["completed_at"],
            effect_reference=row["effect_reference"], effect_hash=row["effect_hash"],
        )


__all__ = [
    "ArtifactRecord",
    "CheckpointRecord",
    "EvidenceLayer",
    "LeaseBindingRecord",
    "RecoveryOperationRecord",
    "ValidationRecord",
]
