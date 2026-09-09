from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional

from durable_execution_evidence import EvidenceLayer
from durable_execution_state import (
    ATTEMPT_STATES,
    LEASE_STATES,
    TASK_STATES,
    DurableExecutionState,
    IntegrityError,
    InvalidTransitionError,
    LineageError,
    RecoveryAmbiguityError,
    StateConflictError,
    utc_now,
)

SAFE_EFFECT_STATES = {"NO_EXTERNAL_EFFECT", "EFFECT_EXPLICITLY_RESOLVED"}
AMBIGUOUS_EFFECT_STATES = {"UNKNOWN", "AMBIGUOUS"}
STALE_SIGNALS = {"LEASE_EXPIRED", "EXPLICIT_WORKER_INTERRUPTION"}


@dataclass(frozen=True)
class LeaseRecoveryResult:
    operation_id: str
    idempotency_key: str
    lease_id: str
    project_id: str
    run_id: str
    phase_id: str
    task_id: str
    attempt_id: str
    lease_state: str
    attempt_state: str
    task_state: str
    recovery_state: str
    effect_state: str


class WorkerLeaseRecovery:
    """Explicit worker/lease recovery over the single durable execution authority."""

    def __init__(self, state: DurableExecutionState) -> None:
        self.state = state
        self.evidence = EvidenceLayer(state)

    def bind_actual_lease(self, *, project_id: str, run_id: str, phase_id: str, task_id: str, attempt_id: str, lease_id: str, worker_id: Optional[str], expected_sequence: Optional[int] = None) -> Any:
        """Bind live worker identity to the exact durable Attempt lineage."""
        with self.state._transaction() as conn:
            task = self.state._require_task(conn, project_id, run_id, phase_id, task_id)
            attempt = self.state._require_attempt(conn, project_id, run_id, phase_id, task_id, attempt_id)
            run = self.state._require_run(conn, project_id, run_id)
            if expected_sequence is not None and int(run["sequence"]) != expected_sequence:
                raise StateConflictError("Stale durable run sequence")
            if task["state"] == "COMPLETED" or attempt["state"] == "VALIDATED":
                raise InvalidTransitionError("A completed task/validated attempt cannot acquire a recovery lease")
        return self.evidence.bind_lease(project_id=project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, lease_id=lease_id, worker_id=worker_id)

    def release(self, *, project_id: str, run_id: str, lease_id: str, reason: str = "normal_release", expected_sequence: Optional[int] = None) -> LeaseRecoveryResult:
        return self._transition(project_id=project_id, run_id=run_id, lease_id=lease_id, new_state="RELEASED", operation_kind="LEASE_RELEASE", idempotency_key=f"lease-release:{lease_id}:{self._stable_reason(reason)}", effect_state="EFFECT_NOT_EVALUATED", expected_sequence=expected_sequence)

    def mark_stale(self, *, project_id: str, run_id: str, lease_id: str, idempotency_key: str, stale_signal: str, expected_sequence: Optional[int] = None) -> LeaseRecoveryResult:
        """Persist a stale lease only from an explicit deterministic signal."""
        if stale_signal not in STALE_SIGNALS:
            raise ValueError("Unsupported stale_signal")
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        return self._transition(project_id=project_id, run_id=run_id, lease_id=lease_id, new_state="STALE", operation_kind="WORKER_LEASE_STALE", idempotency_key=idempotency_key, effect_state="UNKNOWN", expected_sequence=expected_sequence, signal=stale_signal)

    def mark_ambiguous(self, *, project_id: str, run_id: str, lease_id: str, idempotency_key: str, ambiguity_reason: str, expected_sequence: Optional[int] = None) -> LeaseRecoveryResult:
        """Preserve explicit ambiguity; this operation never authorizes retry."""
        if not ambiguity_reason.strip():
            raise ValueError("ambiguity_reason is required")
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        return self._transition(project_id=project_id, run_id=run_id, lease_id=lease_id, new_state="AMBIGUOUS", operation_kind="WORKER_LEASE_AMBIGUOUS", idempotency_key=idempotency_key, effect_state="AMBIGUOUS", expected_sequence=expected_sequence, signal=ambiguity_reason)

    def reclaim(self, *, project_id: str, run_id: str, lease_id: str, idempotency_key: str, effect_state: str, effect_reference: Optional[str] = None, effect_hash: Optional[str] = None, expected_sequence: Optional[int] = None) -> LeaseRecoveryResult:
        """Reclaim only with explicit effect evidence; ambiguity is never retry-safe."""
        if effect_state not in SAFE_EFFECT_STATES | AMBIGUOUS_EFFECT_STATES:
            raise ValueError("Unsupported effect_state")
        if effect_state in AMBIGUOUS_EFFECT_STATES:
            raise RecoveryAmbiguityError("Ambiguous external effect cannot authorize reclaim")
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        if not effect_reference or not effect_hash:
            raise IntegrityError("Safe reclaim requires explicit effect reference and effect hash")
        return self._transition(project_id=project_id, run_id=run_id, lease_id=lease_id, new_state="RECLAIMED", operation_kind="WORKER_LEASE_RECLAIM", idempotency_key=idempotency_key, effect_state=effect_state, effect_reference=effect_reference, effect_hash=effect_hash, expected_sequence=expected_sequence)

    def _transition(self, *, project_id: str, run_id: str, lease_id: str, new_state: str, operation_kind: str, idempotency_key: str, effect_state: str, effect_reference: Optional[str] = None, effect_hash: Optional[str] = None, expected_sequence: Optional[int] = None, signal: Optional[str] = None) -> LeaseRecoveryResult:
        if new_state not in LEASE_STATES:
            raise InvalidTransitionError(f"Unknown lease state: {new_state}")
        with self.state._transaction() as conn:
            lease = conn.execute("SELECT * FROM lease_bindings WHERE lease_id=?", (lease_id,)).fetchone()
            if lease is None:
                raise LineageError(f"Unknown lease: {lease_id}")
            self._require_exact_lineage(lease, project_id, run_id)
            attempt = self.state._require_attempt(conn, project_id, run_id, lease["phase_id"], lease["task_id"], lease["attempt_id"])
            task = self.state._require_task(conn, project_id, run_id, lease["phase_id"], lease["task_id"])
            operation = self._get_or_create_operation(conn, project_id=project_id, run_id=run_id, phase_id=str(lease["phase_id"]), task_id=str(lease["task_id"]), attempt_id=str(lease["attempt_id"]), operation_kind=operation_kind, idempotency_key=idempotency_key)
            current = str(lease["state"])
            if operation["state"] == "COMMITTED" or (current == new_state and operation["state"] == "UNKNOWN"):
                return self._result(operation, lease, attempt, task, effect_state)
            run = self.state._require_run(conn, project_id, run_id)
            if expected_sequence is not None and int(run["sequence"]) != expected_sequence:
                raise StateConflictError("Stale durable run sequence")
            if new_state == "RECLAIMED" and effect_state not in SAFE_EFFECT_STATES:
                raise RecoveryAmbiguityError("Reclaim requires explicit safe effect evidence")
            allowed_from = {"RELEASED": {"ACTIVE"}, "STALE": {"ACTIVE"}, "AMBIGUOUS": {"ACTIVE", "STALE"}, "RECLAIMED": {"STALE", "AMBIGUOUS"}}.get(new_state, set())
            if new_state != current and current not in allowed_from:
                raise InvalidTransitionError(f"Forbidden lease transition: {current} -> {new_state}")

            sequence = int(run["sequence"])
            now = utc_now()
            operation_id = str(operation["operation_id"])
            next_sequence = sequence + 1
            conn.execute("UPDATE recovery_operations SET state='STARTED', started_at=COALESCE(started_at, ?) WHERE operation_id=?", (now, operation_id))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type="RECOVERY_OPERATION_STARTED", entity_type="recovery_operation", entity_id=operation_id, payload={"operation_kind": operation_kind, "idempotency_key": idempotency_key, "lease_id": lease_id, "effect_state": effect_state, "signal": signal})
            sequence = next_sequence

            next_sequence = sequence + 1
            conn.execute("UPDATE lease_bindings SET state=?, released_at=? WHERE lease_id=?", (new_state, now if new_state != "ACTIVE" else lease["released_at"], lease_id))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type=f"LEASE_{new_state}", entity_type="lease", entity_id=lease_id, payload={"phase_id": lease["phase_id"], "task_id": lease["task_id"], "attempt_id": lease["attempt_id"], "worker_id": lease["worker_id"], "state": new_state, "effect_state": effect_state, "signal": signal})
            sequence = next_sequence

            attempt_state = str(attempt["state"])
            task_state = str(task["state"])
            if new_state == "STALE":
                if attempt_state == "STARTED":
                    attempt_state = "INTERRUPTED"
                if task_state == "IN_PROGRESS":
                    task_state = "INTERRUPTED"
            elif new_state == "AMBIGUOUS":
                if attempt_state in {"STARTED", "INTERRUPTED"}:
                    attempt_state = "AMBIGUOUS"
                if task_state == "IN_PROGRESS":
                    task_state = "RECOVERY_REQUIRED"
            elif new_state == "RECLAIMED":
                if attempt_state in {"STARTED", "INTERRUPTED", "AMBIGUOUS"}:
                    attempt_state = "RECOVERY_REQUIRED"
                if task_state in {"IN_PROGRESS", "INTERRUPTED", "RECOVERY_REQUIRED"}:
                    task_state = "RECOVERY_REQUIRED"

            if attempt_state != str(attempt["state"]):
                self._validate_attempt_transition(str(attempt["state"]), attempt_state)
                next_sequence = sequence + 1
                conn.execute("UPDATE attempts SET state=? WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (attempt_state, project_id, run_id, lease["phase_id"], lease["task_id"], lease["attempt_id"]))
                self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type=f"ATTEMPT_{attempt_state}", entity_type="attempt", entity_id=str(lease["attempt_id"]), payload={"task_id": lease["task_id"], "lease_id": lease_id, "lease_state": new_state})
                sequence = next_sequence

            if task_state != str(task["state"]):
                self._validate_task_transition(str(task["state"]), task_state)
                next_sequence = sequence + 1
                conn.execute("UPDATE tasks SET state=?, completed_at=NULL WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (task_state, project_id, run_id, lease["phase_id"], lease["task_id"]))
                self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type=f"TASK_{task_state}", entity_type="task", entity_id=str(lease["task_id"]), payload={"phase_id": lease["phase_id"], "attempt_id": lease["attempt_id"], "lease_id": lease_id})
                sequence = next_sequence

            terminal_operation_state = "COMMITTED" if new_state in {"RELEASED", "RECLAIMED"} else "UNKNOWN"
            next_sequence = sequence + 1
            conn.execute("UPDATE recovery_operations SET state=?, completed_at=?, effect_reference=?, effect_hash=? WHERE operation_id=?", (terminal_operation_state, now if terminal_operation_state == "COMMITTED" else None, effect_reference, effect_hash, operation_id))
            self.state._append_event_tx(conn, project_id=project_id, run_id=run_id, sequence=next_sequence, event_type=f"RECOVERY_OPERATION_{terminal_operation_state}", entity_type="recovery_operation", entity_id=operation_id, payload={"operation_kind": operation_kind, "idempotency_key": idempotency_key, "lease_id": lease_id, "lease_state": new_state, "effect_state": effect_state, "effect_reference": effect_reference, "effect_hash": effect_hash})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, project_id, run_id))
            final_lease = dict(lease) | {"state": new_state, "released_at": now if new_state != "ACTIVE" else lease["released_at"]}
            final_attempt = dict(attempt) | {"state": attempt_state}
            final_task = dict(task) | {"state": task_state}
            final_operation = {"operation_id": operation_id, "idempotency_key": idempotency_key, "state": terminal_operation_state}
            return self._result(final_operation, final_lease, final_attempt, final_task, effect_state)

    def _get_or_create_operation(self, conn: Any, *, project_id: str, run_id: str, phase_id: str, task_id: str, attempt_id: str, operation_kind: str, idempotency_key: str) -> Any:
        existing = conn.execute("SELECT * FROM recovery_operations WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if existing is not None:
            self._require_exact_lineage(existing, project_id, run_id)
            if existing["operation_kind"] != operation_kind:
                raise StateConflictError("Idempotency key is already bound to a different operation kind")
            for field, value in {"phase_id": phase_id, "task_id": task_id, "attempt_id": attempt_id}.items():
                if existing[field] != value:
                    raise LineageError(f"Idempotency key is bound to a different {field}")
            return existing
        operation_id = hashlib.sha256(f"{project_id}|{run_id}|{operation_kind}|{idempotency_key}".encode("utf-8")).hexdigest()[:32]
        conn.execute("INSERT INTO recovery_operations(operation_id, idempotency_key, project_id, run_id, phase_id, task_id, attempt_id, operation_kind, state, started_at, completed_at, effect_reference, effect_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (operation_id, idempotency_key, project_id, run_id, phase_id, task_id, attempt_id, operation_kind, "PLANNED", None, None, None, None))
        return conn.execute("SELECT * FROM recovery_operations WHERE operation_id=?", (operation_id,)).fetchone()

    @staticmethod
    def _validate_attempt_transition(current: str, new: str) -> None:
        allowed = {"STARTED": {"INTERRUPTED", "AMBIGUOUS", "RECOVERY_REQUIRED", "VALIDATED", "FAILED", "FINISHED"}, "INTERRUPTED": {"AMBIGUOUS", "RECOVERY_REQUIRED"}, "AMBIGUOUS": {"RECOVERY_REQUIRED"}, "RECOVERY_REQUIRED": set(), "FINISHED": {"VALIDATED", "FAILED", "RECOVERY_REQUIRED"}, "VALIDATED": set(), "FAILED": set()}
        if new not in ATTEMPT_STATES or new not in allowed.get(current, set()):
            raise InvalidTransitionError(f"Forbidden attempt transition: {current} -> {new}")

    @staticmethod
    def _validate_task_transition(current: str, new: str) -> None:
        allowed = {"PENDING": {"IN_PROGRESS", "INTERRUPTED", "RECOVERY_REQUIRED", "SAFE_STOP"}, "IN_PROGRESS": {"COMPLETED", "FAILED", "INTERRUPTED", "RECOVERY_REQUIRED", "SAFE_STOP"}, "INTERRUPTED": {"RECOVERY_REQUIRED", "IN_PROGRESS", "SAFE_STOP"}, "RECOVERY_REQUIRED": {"IN_PROGRESS", "SAFE_STOP"}, "COMPLETED": set(), "FAILED": set(), "SAFE_STOP": set()}
        if new not in TASK_STATES or new not in allowed.get(current, set()):
            raise InvalidTransitionError(f"Forbidden task transition: {current} -> {new}")

    @staticmethod
    def _require_exact_lineage(row: Any, project_id: str, run_id: str) -> None:
        if str(row["project_id"]) != project_id or str(row["run_id"]) != run_id:
            raise LineageError("Durable recovery object belongs to a different project/run")

    @staticmethod
    def _stable_reason(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _result(operation: Any, lease: Any, attempt: Any, task: Any, effect_state: str) -> LeaseRecoveryResult:
        return LeaseRecoveryResult(operation_id=str(operation["operation_id"]), idempotency_key=str(operation["idempotency_key"]), lease_id=str(lease["lease_id"]), project_id=str(lease["project_id"]), run_id=str(lease["run_id"]), phase_id=str(lease["phase_id"]), task_id=str(lease["task_id"]), attempt_id=str(lease["attempt_id"]), lease_state=str(lease["state"]), attempt_state=str(attempt["state"]), task_state=str(task["state"]), recovery_state=str(operation["state"]), effect_state=effect_state)
