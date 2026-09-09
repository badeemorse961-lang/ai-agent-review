from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from durable_execution_evidence import EvidenceLayer, evidence_digest
from durable_execution_state import (
    ARTIFACT_STATES,
    DELIVERY_STATES,
    DurableExecutionState,
    IntegrityError,
    InvalidTransitionError,
    LineageError,
    StateConflictError,
    WorkspaceEvidence,
    utc_now,
)


@dataclass(frozen=True)
class WorkspaceObservation:
    project_id: str
    run_id: str
    phase_id: str
    task_id: str
    attempt_id: str
    relative_path: str
    observed_state: str
    identity: Optional[str]
    checksum: Optional[str]
    evidence_id: int


@dataclass(frozen=True)
class WorkspaceRecoveryDecision:
    project_id: str
    run_id: str
    phase_id: str
    task_id: str
    attempt_id: str
    classification: str
    action: str
    artifact_id: Optional[str]
    evidence_id: Optional[int]
    recovery_operation_id: Optional[str]
    recovery_operation_key: Optional[str]


@dataclass(frozen=True)
class DeliveryRecoveryDecision:
    project_id: str
    run_id: str
    state_before: str
    state_after: str
    recovery_operation_id: str
    recovery_operation_key: str
    effect_state: str


class WorkspaceDeliveryRecovery:
    """Core authority for actual workspace observation and delivery recovery metadata.

    This layer never writes workspace files, replays patches, starts workers, or
    performs delivery. It records observations and durable recovery decisions
    against the existing DurableExecutionState/EvidenceLayer authority.
    """

    CLASSIFICATIONS = {"COMPLETE", "PARTIAL", "MISMATCH", "ABSENT", "AMBIGUOUS"}

    def __init__(self, state: DurableExecutionState, workspace_root: Path) -> None:
        self.state = state
        self.workspace_root = workspace_root.resolve()
        self.evidence = EvidenceLayer(state)
        self.project_id = "PROJECT-" + hashlib.sha256(str(self.workspace_root).encode("utf-8")).hexdigest()[:24]

    def inspect_artifact(
        self,
        *,
        project_id: str,
        run_id: str,
        phase_id: str,
        task_id: str,
        attempt_id: str,
        artifact_id: str,
        expected_sequence: Optional[int] = None,
    ) -> WorkspaceRecoveryDecision:
        with self.state._transaction() as conn:
            artifact = self.state._require_artifact(conn, artifact_id)
            self._require_lineage(artifact, project_id, run_id, phase_id, task_id, attempt_id)
            run = self.state._require_run(conn, project_id, run_id)
            if expected_sequence is not None and int(run["sequence"]) != expected_sequence:
                raise StateConflictError("Stale durable run sequence")
            relative_path = str(artifact["reference"])
            path = self._safe_path(relative_path)
            observed_identity, checksum, observed_state = self._observe_path(path)
            expected_identity = str(artifact["identity"])
            classification = self._classify_artifact(artifact, observed_state, observed_identity, checksum)
            evidence = WorkspaceEvidence(
                project_id=project_id,
                run_id=run_id,
                phase_id=phase_id,
                task_id=task_id,
                attempt_id=attempt_id,
                relative_path=relative_path,
                change_kind="MODIFIED" if observed_state == "PRESENT_COMPLETE" else "CREATED" if observed_state == "ABSENT" else "MODIFIED",
                expected_before_identity=None,
                observed_before_identity=None,
                expected_after_identity=expected_identity,
                observed_after_identity=observed_identity,
                observed_state=self._evidence_state(classification),
                checkpoint_id=None,
                artifact_id=artifact_id,
                evidence_created_at=utc_now(),
            )
            evidence_id = self._record_evidence_tx(conn, evidence)
            action = self._action_for(classification, artifact["state"])
            operation_id, operation_key = self._record_workspace_operation_tx(
                conn,
                project_id=project_id,
                run_id=run_id,
                phase_id=phase_id,
                task_id=task_id,
                attempt_id=attempt_id,
                artifact_id=artifact_id,
                classification=classification,
                action=action,
                evidence=evidence,
            )
            current_artifact_state = str(artifact["state"])
            if current_artifact_state == "ARTIFACT_VALIDATED" and classification != "COMPLETE":
                if classification in {"MISMATCH", "PARTIAL", "AMBIGUOUS", "ABSENT"}:
                    next_sequence = self._next_sequence(conn, project_id, run_id)
                    conn.execute("UPDATE artifacts SET state='ARTIFACT_INVALID' WHERE artifact_id=?", (artifact_id,))
                    conn.execute(
                        "UPDATE validations SET state='REQUIRES_REVALIDATION' WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=? AND artifact_id=? AND state='PASSED'",
                        (project_id, run_id, phase_id, task_id, attempt_id, artifact_id),
                    )
                    self.state._append_event_tx(
                        conn,
                        project_id=project_id,
                        run_id=run_id,
                        sequence=next_sequence,
                        event_type="WORKSPACE_ARTIFACT_INVALIDATED",
                        entity_type="artifact",
                        entity_id=artifact_id,
                        payload={"classification": classification, "observed_identity": observed_identity, "observed_checksum": checksum, "evidence_id": evidence_id},
                    )
                    self._bump_sequence(conn, project_id, run_id, next_sequence)
            if classification != "COMPLETE" and str(artifact["state"]) == "ARTIFACT_UNVALIDATED":
                pass
            return WorkspaceRecoveryDecision(project_id, run_id, phase_id, task_id, attempt_id, classification, action, artifact_id, evidence_id, operation_id, operation_key)

    def inspect_checkpoint(
        self,
        *,
        project_id: str,
        run_id: str,
        phase_id: str,
        task_id: str,
        attempt_id: str,
        checkpoint_id: str,
        expected_sequence: Optional[int] = None,
    ) -> WorkspaceRecoveryDecision:
        with self.state._transaction() as conn:
            checkpoint = self.state._require_checkpoint(conn, checkpoint_id)
            self._require_lineage(checkpoint, project_id, run_id, phase_id, task_id, attempt_id)
            run = self.state._require_run(conn, project_id, run_id)
            if expected_sequence is not None and int(run["sequence"]) != expected_sequence:
                raise StateConflictError("Stale durable run sequence")
            evidence_rows = conn.execute(
                "SELECT * FROM workspace_evidence WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=? ORDER BY evidence_id DESC",
                (project_id, run_id, phase_id, task_id, attempt_id),
            ).fetchall()
            matching = [row for row in evidence_rows if row["checkpoint_id"] == checkpoint_id and self._row_digest(row) == checkpoint["workspace_evidence_hash"]]
            expected_identity = str(checkpoint["workspace_evidence_identity"])
            path = self._safe_path(str(matching[0]["relative_path"])) if matching else None
            observed_identity, checksum, observed_state = self._observe_path(path) if path else (None, None, "AMBIGUOUS")
            classification = "COMPLETE" if matching and observed_identity == expected_identity else "AMBIGUOUS" if not matching or observed_state == "AMBIGUOUS" else "MISMATCH" if observed_state == "PRESENT_COMPLETE" else "ABSENT"
            evidence_id = None
            operation_id = None
            operation_key = None
            if matching:
                source = matching[0]
                observation = WorkspaceEvidence(
                    project_id=project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id,
                    relative_path=str(source["relative_path"]), change_kind="MODIFIED", expected_before_identity=source["expected_before_identity"],
                    observed_before_identity=source["observed_before_identity"], expected_after_identity=expected_identity, observed_after_identity=observed_identity,
                    observed_state=self._evidence_state(classification), checkpoint_id=checkpoint_id, artifact_id=source["artifact_id"], evidence_created_at=utc_now(),
                )
                evidence_id = self._record_evidence_tx(conn, observation)
                operation_id, operation_key = self._record_workspace_operation_tx(conn, project_id=project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id=source["artifact_id"], classification=classification, action="PRESERVE" if classification == "COMPLETE" else "RECOVERY_REQUIRED", evidence=observation)
            action = "PRESERVE" if classification == "COMPLETE" else "RECOVERY_REQUIRED"
            return WorkspaceRecoveryDecision(project_id, run_id, phase_id, task_id, attempt_id, classification, action, None, evidence_id, operation_id, operation_key)

    def recover_delivery(
        self,
        *,
        project_id: str,
        run_id: str,
        expected_sequence: Optional[int] = None,
        effect_state: Optional[str] = None,
    ) -> DeliveryRecoveryDecision:
        with self.state._transaction() as conn:
            run = self.state._require_run(conn, project_id, run_id)
            current = str(run["delivery_state"])
            if expected_sequence is not None and int(run["sequence"]) != expected_sequence:
                raise StateConflictError("Stale durable run sequence")
            if current not in DELIVERY_STATES:
                raise InvalidTransitionError(f"Unknown delivery state: {current}")
            key = f"m6-delivery-recovery:v1:{project_id}:{run_id}"
            operation = conn.execute("SELECT * FROM recovery_operations WHERE idempotency_key=?", (key,)).fetchone()
            if operation is None:
                operation_id = hashlib.sha256(f"{project_id}|{run_id}|{key}".encode("utf-8")).hexdigest()[:32]
                conn.execute(
                    "INSERT INTO recovery_operations(operation_id,idempotency_key,project_id,run_id,phase_id,task_id,attempt_id,operation_kind,state) VALUES(?,?,?,?,?,?,?,?,?)",
                    (operation_id, key, project_id, run_id, None, None, None, "M6_DELIVERY_RECOVERY", "PLANNED"),
                )
                seq = self._next_sequence(conn, project_id, run_id)
                self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=seq, event_type="RECOVERY_OPERATION_PLANNED", entity_type="recovery_operation", entity_id=operation_id, payload={"operation_kind":"M6_DELIVERY_RECOVERY","idempotency_key":key})
                self._bump_sequence(conn, project_id, run_id, seq)
                operation = conn.execute("SELECT * FROM recovery_operations WHERE operation_id=?", (operation_id,)).fetchone()
            operation_id = str(operation["operation_id"])
            if str(operation["state"]) not in {"COMMITTED", "RECOVERY_REQUIRED", "SAFE_STOP"}:
                seq = self._next_sequence(conn, project_id, run_id)
                now = utc_now()
                conn.execute("UPDATE recovery_operations SET state='UNKNOWN', started_at=COALESCE(started_at,?), effect_reference=?, effect_hash=? WHERE operation_id=?", (now, json.dumps({"effect_state": effect_state or "UNKNOWN", "delivery_state": current}, sort_keys=True, separators=(",", ":")), hashlib.sha256(f"{current}|{effect_state or 'UNKNOWN'}".encode()).hexdigest(), operation_id))
                self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=seq, event_type="RECOVERY_OPERATION_UNKNOWN", entity_type="recovery_operation", entity_id=operation_id, payload={"operation_kind":"M6_DELIVERY_RECOVERY","delivery_state":current,"effect_state":effect_state or "UNKNOWN"})
                self._bump_sequence(conn, project_id, run_id, seq)
                if current in {"DELIVERY_STARTED", "DELIVERY_INTERRUPTED", "DELIVERY_RECOVERY_REQUIRED"}:
                    next_state = "DELIVERY_RECOVERY_REQUIRED"
                    if current != next_state:
                        self._transition_delivery_tx(conn, project_id, run_id, next_state)
            final = self.state._require_run(conn, project_id, run_id)
            return DeliveryRecoveryDecision(project_id, run_id, current, str(final["delivery_state"]), operation_id, key, effect_state or "UNKNOWN")

    def _transition_delivery_tx(self, conn, project_id: str, run_id: str, new_state: str) -> None:
        run = self.state._require_run(conn, project_id, run_id)
        current = str(run["delivery_state"])
        allowed = {
            "DELIVERY_PENDING": {"DELIVERY_STARTED"},
            "DELIVERY_STARTED": {"DELIVERY_INTERRUPTED", "DELIVERY_COMMITTED", "DELIVERY_RECOVERY_REQUIRED"},
            "DELIVERY_INTERRUPTED": {"DELIVERY_STARTED", "DELIVERY_RECOVERY_REQUIRED", "DELIVERY_COMMITTED"},
            "DELIVERY_RECOVERY_REQUIRED": {"DELIVERY_STARTED", "DELIVERY_COMMITTED"},
            "DELIVERY_COMMITTED": {"DELIVERY_VERIFIED"},
            "DELIVERY_VERIFIED": set(),
        }
        if new_state not in DELIVERY_STATES or new_state not in allowed.get(current, set()):
            raise InvalidTransitionError(f"Forbidden delivery transition: {current} -> {new_state}")
        seq = self._next_sequence(conn, project_id, run_id)
        self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=seq, event_type=new_state, entity_type="delivery", entity_id=run_id, payload={"delivery_state":new_state})
        self._bump_sequence(conn, project_id, run_id, seq)
        conn.execute("UPDATE runs SET delivery_state=? WHERE project_id=? AND run_id=?", (new_state, project_id, run_id))

    def _record_evidence_tx(self, conn, evidence: WorkspaceEvidence) -> int:
        self.state._require_attempt(conn, evidence.project_id, evidence.run_id, evidence.phase_id, evidence.task_id, evidence.attempt_id)
        cur = conn.execute(
            "INSERT INTO workspace_evidence(project_id,run_id,phase_id,task_id,attempt_id,relative_path,change_kind,expected_before_identity,observed_before_identity,expected_after_identity,observed_after_identity,observed_state,checkpoint_id,artifact_id,evidence_created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (evidence.project_id,evidence.run_id,evidence.phase_id,evidence.task_id,evidence.attempt_id,evidence.relative_path,evidence.change_kind,evidence.expected_before_identity,evidence.observed_before_identity,evidence.expected_after_identity,evidence.observed_after_identity,evidence.observed_state,evidence.checkpoint_id,evidence.artifact_id,evidence.evidence_created_at),
        )
        evidence_id = int(cur.lastrowid)
        seq = self._next_sequence(conn, evidence.project_id, evidence.run_id)
        self.state._append_event_tx(conn, project_id=evidence.project_id, run_id=evidence.run_id, sequence=seq, event_type="WORKSPACE_EVIDENCE_RECORDED", entity_type="workspace_evidence", entity_id=str(evidence_id), payload={"phase_id":evidence.phase_id,"task_id":evidence.task_id,"attempt_id":evidence.attempt_id,"relative_path":evidence.relative_path,"observed_state":evidence.observed_state,"artifact_id":evidence.artifact_id,"checkpoint_id":evidence.checkpoint_id,"evidence_digest":evidence_digest(evidence)})
        self._bump_sequence(conn, evidence.project_id, evidence.run_id, seq)
        return evidence_id

    def _record_workspace_operation_tx(self, conn, *, project_id, run_id, phase_id, task_id, attempt_id, artifact_id, classification, action, evidence):
        key = f"m6-workspace:v1:{project_id}:{run_id}:{phase_id}:{task_id}:{attempt_id}:{artifact_id or 'checkpoint'}:{classification}"
        existing = conn.execute("SELECT * FROM recovery_operations WHERE idempotency_key=?", (key,)).fetchone()
        if existing is not None:
            return str(existing["operation_id"]), key
        operation_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        conn.execute("INSERT INTO recovery_operations(operation_id,idempotency_key,project_id,run_id,phase_id,task_id,attempt_id,operation_kind,state,effect_reference,effect_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (operation_id,key,project_id,run_id,phase_id,task_id,attempt_id,"M6_WORKSPACE_RECOVERY","COMMITTED",json.dumps({"classification":classification,"action":action,"evidence_id":"pending"}, sort_keys=True, separators=(",", ":")), hashlib.sha256(f"{key}|{classification}|{action}".encode()).hexdigest()))
        seq = self._next_sequence(conn, project_id, run_id)
        self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=seq, event_type="M6_WORKSPACE_RECOVERY_DECISION", entity_type="recovery_operation", entity_id=operation_id, payload={"operation_kind":"M6_WORKSPACE_RECOVERY","idempotency_key":key,"classification":classification,"action":action,"artifact_id":artifact_id,"relative_path":evidence.relative_path,"effect_state":"NO_EXTERNAL_EFFECT"})
        self._bump_sequence(conn, project_id, run_id, seq)
        return operation_id, key

    @staticmethod
    def _require_lineage(row, project_id, run_id, phase_id, task_id, attempt_id):
        if (row["project_id"],row["run_id"],row["phase_id"],row["task_id"],row["attempt_id"]) != (project_id,run_id,phase_id,task_id,attempt_id):
            raise LineageError("Cross-execution lineage reference rejected")

    def _safe_path(self, relative_path: str) -> Path:
        raw = Path(relative_path)
        path = (self.workspace_root / raw).resolve() if not raw.is_absolute() else raw.resolve()
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise LineageError("Workspace reference escapes project root") from exc
        return path

    @staticmethod
    def _observe_path(path: Optional[Path]):
        if path is None:
            return None, None, "AMBIGUOUS"
        if not path.exists():
            return None, None, "ABSENT"
        if not path.is_file():
            return None, None, "AMBIGUOUS"
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        return f"sha256:{digest}", digest, "PRESENT_COMPLETE"

    @classmethod
    def _classify_artifact(cls, artifact, observed_state, observed_identity, observed_checksum):
        if observed_state == "ABSENT":
            return "ABSENT"
        if observed_state == "AMBIGUOUS":
            return "AMBIGUOUS"
        if observed_identity != str(artifact["identity"]):
            return "MISMATCH"
        if artifact["checksum"] is not None and observed_checksum != artifact["checksum"]:
            return "MISMATCH"
        if str(artifact["state"]) == "ARTIFACT_VALIDATED":
            return "COMPLETE"
        return "PARTIAL"

    @staticmethod
    def _action_for(classification, artifact_state):
        if classification == "COMPLETE" and artifact_state == "ARTIFACT_VALIDATED":
            return "PRESERVE"
        if classification in {"PARTIAL", "MISMATCH", "ABSENT", "AMBIGUOUS"}:
            return "RECOVERY_REQUIRED"
        return "RECOVERY_REQUIRED"

    @staticmethod
    def _evidence_state(classification):
        return {"COMPLETE":"PRESENT_COMPLETE","PARTIAL":"PRESENT_PARTIAL","MISMATCH":"MISMATCH","ABSENT":"ABSENT","AMBIGUOUS":"AMBIGUOUS"}[classification]

    @staticmethod
    def _row_digest(row):
        payload = {k: row[k] for k in ("project_id","run_id","phase_id","task_id","attempt_id","relative_path","change_kind","expected_before_identity","observed_before_identity","expected_after_identity","observed_after_identity","observed_state","checkpoint_id","artifact_id","evidence_created_at")}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _next_sequence(conn, project_id, run_id):
        row = conn.execute("SELECT sequence FROM runs WHERE project_id=? AND run_id=?", (project_id, run_id)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return int(row["sequence"]) + 1

    @staticmethod
    def _bump_sequence(conn, project_id, run_id, sequence):
        conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (sequence, project_id, run_id))


__all__ = ["WorkspaceDeliveryRecovery", "WorkspaceObservation", "WorkspaceRecoveryDecision", "DeliveryRecoveryDecision"]
