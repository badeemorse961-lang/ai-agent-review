from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from durable_execution_evidence import EvidenceLayer
from durable_execution_state import DurableExecutionState, IntegrityError, LineageError, RecoveryAmbiguityError, StateConflictError
from worker_lease_recovery import WorkerLeaseRecovery


@dataclass(frozen=True)
class StartupRecoveryDecision:
    run_id: str
    project_id: str
    state_before: str
    state_after: str
    recovery_operation_id: Optional[str]
    recovery_operation_key: Optional[str]
    decisions: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StartupRecoveryReport:
    project_id: str
    workspace_root: str
    discovered_runs: tuple[str, ...]
    decisions: tuple[StartupRecoveryDecision, ...]
    safe_stop: bool = False
    reason: Optional[str] = None


class StartupRecoverySafetyStop(RuntimeError):
    """Raised when startup cannot establish a trustworthy recovery boundary."""


class StartupRecovery:
    """Deterministic startup discovery/reconciliation over the single durable state authority.

    This class never restores files, starts workers, retries tasks, or performs delivery.
    It only discovers persisted incomplete execution, validates durable lineage/integrity,
    and records bounded recovery decisions.
    """

    SCHEMA_VERSION = 1

    def __init__(self, state: DurableExecutionState, workspace_root: Path) -> None:
        self.state = state
        self.workspace_root = workspace_root.resolve()
        self.project_id = "PROJECT-" + hashlib.sha256(str(self.workspace_root).encode("utf-8")).hexdigest()[:24]
        self.evidence = EvidenceLayer(state)
        self.worker_recovery = WorkerLeaseRecovery(state)

    def recover(self) -> StartupRecoveryReport:
        project = self._load_project()
        if project is None:
            return StartupRecoveryReport(self.project_id, str(self.workspace_root), (), ())
        self._validate_project_binding(project)
        run_ids = self._run_ids()
        decisions: list[StartupRecoveryDecision] = []
        for run_id in run_ids:
            try:
                self.evidence.verify_integrity(project_id=self.project_id, run_id=run_id)
                self._validate_lineage(run_id)
                decision = self._recover_run(run_id)
                if decision is not None:
                    decisions.append(decision)
            except (IntegrityError, LineageError) as exc:
                raise StartupRecoverySafetyStop(f"Startup recovery stopped for run {run_id!r}: {exc}") from exc
        return StartupRecoveryReport(self.project_id, str(self.workspace_root), tuple(item.run_id for item in decisions), tuple(decisions))

    def _load_project(self) -> Any:
        with self.state._lock:
            return self.state._connection.execute("SELECT * FROM projects WHERE project_id=?", (self.project_id,)).fetchone()

    def _validate_project_binding(self, project: Any) -> None:
        recorded = Path(str(project["workspace_root"])).resolve()
        if recorded != self.workspace_root:
            raise StartupRecoverySafetyStop("Durable project is bound to a different workspace")
        if str(project["project_id"]) != self.project_id:
            raise StartupRecoverySafetyStop("Durable project identity mismatch")

    def _run_ids(self) -> tuple[str, ...]:
        with self.state._lock:
            rows = self.state._connection.execute("SELECT run_id FROM runs WHERE project_id=? ORDER BY created_at, run_id", (self.project_id,)).fetchall()
        return tuple(str(row["run_id"]) for row in rows)

    def _validate_lineage(self, run_id: str) -> None:
        with self.state._lock:
            conn = self.state._connection
            self.state._require_run(conn, self.project_id, run_id)
            phases = conn.execute("SELECT * FROM phases WHERE project_id=? AND run_id=? ORDER BY ordinal, phase_id", (self.project_id, run_id)).fetchall()
            for phase in phases:
                self.state._require_phase(conn, self.project_id, run_id, str(phase["phase_id"]))
            tasks = conn.execute("SELECT * FROM tasks WHERE project_id=? AND run_id=? ORDER BY phase_id, task_id", (self.project_id, run_id)).fetchall()
            for task in tasks:
                self.state._require_task(conn, self.project_id, run_id, str(task["phase_id"]), str(task["task_id"]))
            attempts = conn.execute("SELECT * FROM attempts WHERE project_id=? AND run_id=? ORDER BY phase_id, task_id, attempt_id", (self.project_id, run_id)).fetchall()
            for attempt in attempts:
                self.state._require_attempt(conn, self.project_id, run_id, str(attempt["phase_id"]), str(attempt["task_id"]), str(attempt["attempt_id"]))
                if attempt["lease_id"] is not None:
                    lease = conn.execute("SELECT * FROM lease_bindings WHERE lease_id=?", (attempt["lease_id"],)).fetchone()
                    if lease is None:
                        raise LineageError("Attempt references missing lease")
                    if (lease["project_id"], lease["run_id"], lease["phase_id"], lease["task_id"], lease["attempt_id"]) != (self.project_id, run_id, attempt["phase_id"], attempt["task_id"], attempt["attempt_id"]):
                        raise LineageError("Attempt lease lineage mismatch")
            leases = conn.execute("SELECT * FROM lease_bindings WHERE project_id=? AND run_id=? ORDER BY lease_id", (self.project_id, run_id)).fetchall()
            for lease in leases:
                self.state._require_attempt(conn, self.project_id, run_id, str(lease["phase_id"]), str(lease["task_id"]), str(lease["attempt_id"]))
            operations = conn.execute("SELECT * FROM recovery_operations WHERE project_id=? AND run_id=? ORDER BY operation_id", (self.project_id, run_id)).fetchall()
            for operation in operations:
                if operation["phase_id"] is not None:
                    self.state._require_phase(conn, self.project_id, run_id, str(operation["phase_id"]))
                if operation["task_id"] is not None:
                    self.state._require_task(conn, self.project_id, run_id, str(operation["phase_id"]), str(operation["task_id"]))
                if operation["attempt_id"] is not None:
                    self.state._require_attempt(conn, self.project_id, run_id, str(operation["phase_id"]), str(operation["task_id"]), str(operation["attempt_id"]))

    def _recover_run(self, run_id: str) -> Optional[StartupRecoveryDecision]:
        with self.state._lock:
            run = self.state._connection.execute("SELECT * FROM runs WHERE project_id=? AND run_id=?", (self.project_id, run_id)).fetchone()
        if run is None or str(run["state"]) == "COMPLETED":
            return None
        candidate, reasons = self._candidate_state(run_id, str(run["state"]))
        if not candidate:
            return None
        state_before = str(run["state"])
        decisions = list(reasons)
        operation = self._startup_operation(run_id, reasons)
        if operation.state == "PLANNED":
            operation = self.evidence.transition_recovery_operation(project_id=self.project_id, run_id=run_id, operation_id=operation.operation_id, new_state="STARTED")
        if operation.state in {"STARTED", "EFFECT_OBSERVED"}:
            operation = self.evidence.transition_recovery_operation(project_id=self.project_id, run_id=run_id, operation_id=operation.operation_id, new_state="UNKNOWN", effect_reference=self._decision_reference(run_id, reasons), effect_hash=self._decision_hash(run_id, reasons))
        decisions.extend(self._reconcile_active_leases(run_id))
        current = self.state.get_run(run_id, project_id=self.project_id)
        if current.state in {"RUNNING", "CREATED", "PLAN_ACCEPTED"}:
            self.state.transition_run(project_id=self.project_id, run_id=run_id, expected_sequence=current.sequence, new_state="RECOVERING", event_type="STARTUP_RECOVERY_STARTED", entity_id=run_id, payload={"decision": "RECOVERY_REQUIRED", "reason_count": len(decisions)})
        current = self.state.get_run(run_id, project_id=self.project_id)
        if current.state == "RECOVERING":
            self.state.transition_run(project_id=self.project_id, run_id=run_id, expected_sequence=current.sequence, new_state="RECOVERY_REQUIRED", event_type="STARTUP_RECOVERY_REQUIRED", entity_id=run_id, payload={"decision": "RECOVERY_REQUIRED", "reasons": tuple(sorted(set(decisions)))})
        return StartupRecoveryDecision(run_id, self.project_id, state_before, self.state.get_run(run_id, project_id=self.project_id).state, operation.operation_id, operation.idempotency_key, tuple(sorted(set(decisions))))

    def _startup_operation(self, run_id: str, reasons: list[str]) -> Any:
        with self.state._lock:
            existing = self.state._connection.execute("SELECT * FROM recovery_operations WHERE project_id=? AND run_id=? AND operation_kind='STARTUP_INTERRUPTED_RUN_DISCOVERY' ORDER BY operation_id LIMIT 1", (self.project_id, run_id)).fetchone()
        if existing is not None:
            return self.evidence.create_recovery_operation(project_id=self.project_id, run_id=run_id, operation_kind="STARTUP_INTERRUPTED_RUN_DISCOVERY", idempotency_key=str(existing["idempotency_key"]))
        return self.evidence.create_recovery_operation(project_id=self.project_id, run_id=run_id, operation_kind="STARTUP_INTERRUPTED_RUN_DISCOVERY", idempotency_key=f"startup-recovery:v1:{self.project_id}:{run_id}")

    def _candidate_state(self, run_id: str, run_state: str) -> tuple[bool, list[str]]:
        with self.state._lock:
            conn = self.state._connection
            reasons: list[str] = []
            if run_state == "RUNNING":
                reasons.append("RUNNING_RUN_AT_STARTUP")
            if run_state in {"CREATED", "PLAN_ACCEPTED"} and int(conn.execute("SELECT COUNT(*) FROM tasks WHERE project_id=? AND run_id=? AND state<>?", (self.project_id, run_id, "PENDING")).fetchone()[0]) > 0:
                reasons.append("CHILD_WORK_STARTED_BEFORE_RUN_TERMINAL")
            if int(conn.execute("SELECT COUNT(*) FROM lease_bindings WHERE project_id=? AND run_id=? AND state IN ('ACTIVE','STALE','AMBIGUOUS')", (self.project_id, run_id)).fetchone()[0]) > 0:
                reasons.append("NON_TERMINAL_LEASE_PRESENT")
            if int(conn.execute("SELECT COUNT(*) FROM tasks WHERE project_id=? AND run_id=? AND state IN ('INTERRUPTED','RECOVERY_REQUIRED')", (self.project_id, run_id)).fetchone()[0]) > 0:
                reasons.append("INTERRUPTED_OR_RECOVERY_REQUIRED_TASK")
            if int(conn.execute("SELECT COUNT(*) FROM attempts WHERE project_id=? AND run_id=? AND state IN ('STARTED','INTERRUPTED','AMBIGUOUS','RECOVERY_REQUIRED')", (self.project_id, run_id)).fetchone()[0]) > 0:
                reasons.append("NON_TERMINAL_ATTEMPT_PRESENT")
            if int(conn.execute("SELECT COUNT(*) FROM recovery_operations WHERE project_id=? AND run_id=? AND state IN ('PLANNED','STARTED','EFFECT_OBSERVED','UNKNOWN')", (self.project_id, run_id)).fetchone()[0]) > 0:
                reasons.append("NON_TERMINAL_RECOVERY_OPERATION_PRESENT")
        return bool(reasons), reasons

    def _reconcile_active_leases(self, run_id: str) -> list[str]:
        decisions: list[str] = []
        with self.state._lock:
            leases = self.state._connection.execute("SELECT * FROM lease_bindings WHERE project_id=? AND run_id=? AND state='ACTIVE' ORDER BY lease_id", (self.project_id, run_id)).fetchall()
        for lease in leases:
            lease_id = str(lease["lease_id"])
            key = f"startup-lease-ambiguity:v1:{self.project_id}:{run_id}:{lease_id}"
            try:
                result = self.worker_recovery.mark_ambiguous(project_id=self.project_id, run_id=run_id, lease_id=lease_id, idempotency_key=key, ambiguity_reason="Startup cannot prove worker survival or external-effect absence")
            except RecoveryAmbiguityError:
                decisions.append("ACTIVE_LEASE_EFFECT_AMBIGUOUS")
                continue
            if result.lease_state != "AMBIGUOUS":
                raise IntegrityError("Startup lease reconciliation did not produce AMBIGUOUS state")
            decisions.append("ACTIVE_LEASE_RETAINED_AS_AMBIGUOUS")
        return decisions

    @staticmethod
    def _decision_reference(run_id: str, reasons: list[str]) -> str:
        payload = {"schema_version": 1, "run_id": run_id, "decision": "RECOVERY_REQUIRED", "reasons": sorted(set(reasons)), "effect_state": "UNKNOWN"}
        return "startup-recovery://" + json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decision_hash(run_id: str, reasons: list[str]) -> str:
        return hashlib.sha256(StartupRecovery._decision_reference(run_id, reasons).encode("utf-8")).hexdigest()


__all__ = ["StartupRecovery", "StartupRecoveryDecision", "StartupRecoveryReport", "StartupRecoverySafetyStop"]
