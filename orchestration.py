from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from central_leader import CentralLeader, LeaderResponse
from durable_execution_evidence import EvidenceLayer, evidence_digest
from durable_execution_state import DurableExecutionState, LineageError, WorkspaceEvidence, utc_now
from execution_authorization import ExecutionAuthorizationBoundary
from execution_gate import FileChange
from independent_validation import IndependentValidator, ValidationHook, ValidationVerdict
from plan_decomposer import PlanDecomposer
from worker_dispatch import WorkerAssignment, WorkerDispatcher
from worker_execution import ExecutionRequest, ExecutionResult, WorkerExecutionBoundary
from worker_work_product import WorkerWorkProduct

SCHEMA_VERSION = 1

class OrchestrationError(ValueError):
    """Base error raised by the canonical orchestration boundary."""

class OrchestrationSafetyStop(OrchestrationError):
    """Raised when the composed flow cannot proceed safely."""

@dataclass(frozen=True)
class WorkerExecutionSpec:
    """Explicit adapter output for one worker task."""
    command: tuple[str, ...]
    targets: tuple[str, ...]
    changed_targets: tuple[str, ...]
    changes: tuple[FileChange, ...]
    external_reads: tuple[str, ...] = ()
    external_writes: tuple[str, ...] = ()

class ProjectUnderstandingAdapter(Protocol):
    def analyze(self) -> Mapping[str, Any]: ...

class WorkerAdapter(Protocol):
    def prepare(self, task: Mapping[str, Any], assignment: Mapping[str, Any]) -> WorkerExecutionSpec: ...
    def validate(self, request: ExecutionRequest, task: Mapping[str, Any], result: ExecutionResult, spec: WorkerExecutionSpec) -> Mapping[str, Any]: ...

@dataclass(frozen=True)
class TaskExecutionRecord:
    task: Mapping[str, Any]
    assignment: Mapping[str, Any]
    execution_request: ExecutionRequest
    execution_result: ExecutionResult
    validation: ValidationVerdict
    work_product: WorkerWorkProduct
    authorization: Mapping[str, Any]
    transaction: Mapping[str, Any]

@dataclass(frozen=True)
class OrchestrationResult:
    status: str
    task_id: str
    understanding: Mapping[str, Any]
    leader_response: LeaderResponse
    plan: Mapping[str, Any]
    assignments: tuple[WorkerAssignment, ...]
    task_records: tuple[TaskExecutionRecord, ...]
    durable_project_id: str | None = None
    durable_run_id: str | None = None
    durable_phase_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "task_id": self.task_id,
            "understanding": dict(self.understanding),
            "leader_response": {"payload": self.leader_response.payload, "account_id": self.leader_response.account_id, "model": self.leader_response.model, "tier": self.leader_response.tier},
            "plan": dict(self.plan),
            "assignments": [item.to_dict() for item in self.assignments],
            "task_records": [{"task": dict(r.task), "assignment": dict(r.assignment), "execution_request": r.execution_request.to_dict(), "execution_result": r.execution_result.to_dict(), "validation": r.validation.to_dict(), "work_product": r.work_product.to_dict(), "authorization": dict(r.authorization), "transaction": dict(r.transaction)} for r in self.task_records],
            "durable_project_id": self.durable_project_id,
            "durable_run_id": self.durable_run_id,
            "durable_phase_id": self.durable_phase_id,
        }

class _DurableLifecycleBridge:
    """Thin adapter from canonical sequencing to the existing M1/M2 authority."""
    def __init__(self, state: DurableExecutionState, workspace_root: Path) -> None:
        self.state = state
        self.workspace_root = workspace_root.resolve()
        self.project_id = "PROJECT-" + hashlib.sha256(str(self.workspace_root).encode("utf-8")).hexdigest()[:24]

    def create_run(self) -> str:
        self.ensure_project()
        return self.state.create_run(self.project_id).run_id

    def ensure_project(self) -> None:
        with self.state._transaction() as conn:
            row = conn.execute("SELECT workspace_root FROM projects WHERE project_id=?", (self.project_id,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO projects(project_id, workspace_root, created_at, state) VALUES(?,?,?,?)", (self.project_id, str(self.workspace_root), utc_now(), "ACTIVE"))
            elif Path(str(row["workspace_root"])).resolve() != self.workspace_root:
                raise LineageError("Durable project is bound to a different workspace")

    def accept_plan(self, run_id: str, task_id: str, plan: Mapping[str, Any]) -> None:
        run = self.state.get_run(run_id, project_id=self.project_id)
        if run.state == "CREATED":
            self.state.transition_run(project_id=self.project_id, run_id=run_id, expected_sequence=run.sequence, new_state="PLAN_ACCEPTED", event_type="PLAN_ACCEPTED", entity_id=run_id, payload={"task_id": task_id, "task_count": len(plan.get("tasks", [])) if isinstance(plan.get("tasks"), list) else 0})
        elif run.state != "PLAN_ACCEPTED":
            raise OrchestrationSafetyStop(f"Durable run cannot accept plan from {run.state!r}")

    def start_phase(self, run_id: str, phase_id: str) -> None:
        self._insert_phase(run_id, phase_id)
        self._transition_child(run_id, "phase", phase_id, "IN_PROGRESS", event_type="PHASE_STARTED")

    def start_task(self, run_id: str, phase_id: str, task: Mapping[str, Any]) -> None:
        task_id = str(task["task_id"])
        self._insert_task(run_id, phase_id, task)
        self._transition_child(run_id, "task", task_id, "IN_PROGRESS", event_type="TASK_STARTED", phase_id=phase_id)

    def start_attempt(self, run_id: str, phase_id: str, task_id: str, attempt_id: str, worker_id: str) -> None:
        with self.state._transaction() as conn:
            self.state._require_task(conn, self.project_id, run_id, phase_id, task_id)
            run = self.state._require_run(conn, self.project_id, run_id)
            existing = conn.execute("SELECT * FROM attempts WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (self.project_id, run_id, phase_id, task_id, attempt_id)).fetchone()
            if existing is not None:
                if existing["worker_id"] != worker_id:
                    raise LineageError("Attempt identity maps to a different worker")
                return
            next_sequence = int(run["sequence"]) + 1
            conn.execute("INSERT INTO attempts(attempt_id, project_id, run_id, phase_id, task_id, worker_id, lease_id, started_at, finished_at, state) VALUES(?,?,?,?,?,?,?,?,?,?)", (attempt_id, self.project_id, run_id, phase_id, task_id, worker_id, None, utc_now(), None, "STARTED"))
            self.state._append_event_tx(conn, project_id=self.project_id, run_id=run_id, sequence=next_sequence, event_type="ATTEMPT_STARTED", entity_type="attempt", entity_id=attempt_id, payload={"phase_id": phase_id, "task_id": task_id, "worker_id": worker_id})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, self.project_id, run_id))

    def persist_post_execution(self, run_id: str, phase_id: str, task_id: str, attempt_id: str, raw_checkpoint_id: str, before_identity: str, after_identity: str, observed_state: str) -> tuple[str, str, str, int]:
        artifact_id = f"{run_id}:{task_id}:ARTIFACT:1"
        artifact_identity = self._artifact_identity(task_id, after_identity)
        layer = EvidenceLayer(self.state)
        layer.register_artifact(project_id=self.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id=artifact_id, reference=f"artifact://{run_id}/{task_id}", identity=artifact_identity, checksum=artifact_identity)
        evidence = WorkspaceEvidence(project_id=self.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, relative_path=".", change_kind="MODIFIED", expected_before_identity=before_identity, observed_before_identity=before_identity, expected_after_identity=after_identity, observed_after_identity=after_identity, observed_state=observed_state, checkpoint_id=None, artifact_id=artifact_id, evidence_created_at=utc_now())
        evidence_id = None
        with self.state._lock:
            digest = evidence_digest(evidence)
            rows = self.state._connection.execute("SELECT * FROM workspace_evidence WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=? ORDER BY evidence_id DESC LIMIT 10", (self.project_id, run_id, phase_id, task_id, attempt_id)).fetchall()
            for row in rows:
                if EvidenceLayer._evidence_row_digest(row) == digest:
                    evidence_id = int(row["evidence_id"])
                    evidence = self._evidence_from_row(row)
                    break
        if evidence_id is None:
            evidence_id = layer.record_workspace_evidence(evidence)
        checkpoint_id = f"{run_id}:{raw_checkpoint_id}"
        checkpoint = layer.create_checkpoint(project_id=self.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity=after_identity, workspace_evidence_hash=evidence_digest(evidence), checkpoint_id=checkpoint_id)
        if checkpoint.status == "CREATED":
            layer.transition_checkpoint(project_id=self.project_id, run_id=run_id, checkpoint_id=checkpoint_id, new_status="TRUSTED")
        layer.validate_artifact(project_id=self.project_id, run_id=run_id, artifact_id=artifact_id, observed_identity=artifact_identity, observed_checksum=artifact_identity)
        return checkpoint_id, evidence_digest(evidence), artifact_id, checkpoint.sequence

    def create_and_pass_validation(self, run_id: str, phase_id: str, task_id: str, attempt_id: str, checkpoint_sequence: int, evidence_hash: str, artifact_id: str) -> str:
        validation_id = f"{run_id}:{task_id}:VALIDATION:1"
        layer = EvidenceLayer(self.state)
        validation = layer.create_validation(project_id=self.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, checkpoint_sequence=checkpoint_sequence, validation_id=validation_id, artifact_id=artifact_id)
        if validation.state == "PENDING":
            layer.transition_validation(project_id=self.project_id, run_id=run_id, validation_id=validation_id, new_state="PASSED", evidence_hash=evidence_hash)
        return validation_id

    def complete_task(self, run_id: str, phase_id: str, task_id: str, attempt_id: str, validation_id: str) -> None:
        with self.state._lock:
            row = self.state._connection.execute("SELECT state FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (self.project_id, run_id, phase_id, task_id)).fetchone()
        if row is not None and row["state"] == "COMPLETED":
            return
        layer = EvidenceLayer(self.state)
        if not layer.task_completion_ready(project_id=self.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, validation_id=validation_id):
            raise OrchestrationSafetyStop("Durable task completion precondition failed")
        layer.complete_task(project_id=self.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, validation_id=validation_id)

    def finish(self, run_id: str, phase_id: str) -> None:
        self._transition_child(run_id, "phase", phase_id, "COMPLETED", event_type="PHASE_COMPLETED")
        run = self.state.get_run(run_id, project_id=self.project_id)
        if run.state == "RUNNING":
            self.state.transition_run(project_id=self.project_id, run_id=run_id, expected_sequence=run.sequence, new_state="COMPLETED", event_type="RUN_COMPLETED")

    def start_running(self, run_id: str) -> None:
        run = self.state.get_run(run_id, project_id=self.project_id)
        if run.state == "PLAN_ACCEPTED":
            self.state.transition_run(project_id=self.project_id, run_id=run_id, expected_sequence=run.sequence, new_state="RUNNING", event_type="RUN_STARTED")
        elif run.state != "RUNNING":
            raise OrchestrationSafetyStop(f"Durable run cannot start from {run.state!r}")

    def _insert_phase(self, run_id: str, phase_id: str) -> None:
        with self.state._transaction() as conn:
            self.state._require_run(conn, self.project_id, run_id)
            if conn.execute("SELECT 1 FROM phases WHERE project_id=? AND run_id=? AND phase_id=?", (self.project_id, run_id, phase_id)).fetchone() is not None:
                return
            run = self.state._require_run(conn, self.project_id, run_id)
            next_sequence = int(run["sequence"]) + 1
            conn.execute("INSERT INTO phases(phase_id, project_id, run_id, ordinal, name, state) VALUES(?,?,?,?,?,?)", (phase_id, self.project_id, run_id, 1, "Canonical execution phase", "PENDING"))
            self.state._append_event_tx(conn, project_id=self.project_id, run_id=run_id, sequence=next_sequence, event_type="PHASE_CREATED", entity_type="phase", entity_id=phase_id, payload={"phase_id": phase_id})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, self.project_id, run_id))

    def _insert_task(self, run_id: str, phase_id: str, task: Mapping[str, Any]) -> None:
        task_id = str(task["task_id"])
        with self.state._transaction() as conn:
            self.state._require_phase(conn, self.project_id, run_id, phase_id)
            if conn.execute("SELECT 1 FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (self.project_id, run_id, phase_id, task_id)).fetchone() is not None:
                return
            run = self.state._require_run(conn, self.project_id, run_id)
            deps = task.get("depends_on", [])
            next_sequence = int(run["sequence"]) + 1
            conn.execute("INSERT INTO tasks(task_id, project_id, run_id, phase_id, state, task_kind, retry_class, depends_on_json, latest_attempt_id, completed_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (task_id, self.project_id, run_id, phase_id, "PENDING", str(task.get("objective") or "execution"), str(task.get("retry_class") or "IDEMPOTENT"), json.dumps(deps, sort_keys=True), None, None))
            self.state._append_event_tx(conn, project_id=self.project_id, run_id=run_id, sequence=next_sequence, event_type="TASK_CREATED", entity_type="task", entity_id=task_id, payload={"phase_id": phase_id, "task_id": task_id})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, self.project_id, run_id))

    def _transition_child(self, run_id: str, kind: str, entity_id: str, new_state: str, *, event_type: str, phase_id: str | None = None) -> None:
        table = "phases" if kind == "phase" else "tasks"
        with self.state._transaction() as conn:
            run = self.state._require_run(conn, self.project_id, run_id)
            if kind == "phase":
                row = conn.execute("SELECT * FROM phases WHERE project_id=? AND run_id=? AND phase_id=?", (self.project_id, run_id, entity_id)).fetchone()
                where_sql = "project_id=? AND run_id=? AND phase_id=?"
                where_args = (self.project_id, run_id, entity_id)
            else:
                row = conn.execute("SELECT * FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (self.project_id, run_id, phase_id, entity_id)).fetchone()
                where_sql = "project_id=? AND run_id=? AND phase_id=? AND task_id=?"
                where_args = (self.project_id, run_id, phase_id, entity_id)
            if row is None:
                raise LineageError(f"Unknown {kind}: {entity_id}")
            if str(row["state"]) == new_state:
                return
            next_sequence = int(run["sequence"]) + 1
            conn.execute(f"UPDATE {table} SET state=? WHERE {where_sql}", (new_state, *where_args))
            self.state._append_event_tx(conn, project_id=self.project_id, run_id=run_id, sequence=next_sequence, event_type=event_type, entity_type=kind, entity_id=entity_id, payload={"state": new_state, "phase_id": phase_id})
            conn.execute("UPDATE runs SET sequence=? WHERE project_id=? AND run_id=?", (next_sequence, self.project_id, run_id))

    @staticmethod
    def _artifact_identity(task_id: str, after_identity: str) -> str:
        return hashlib.sha256(json.dumps({"task_id": task_id, "after": after_identity}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _workspace_identity(self, targets: tuple[str, ...]) -> str:
        entries: list[tuple[str, str]] = []
        for target in sorted(set(targets)):
            candidate = (self.workspace_root / target).resolve(strict=False)
            try:
                candidate.relative_to(self.workspace_root)
            except ValueError as exc:
                raise OrchestrationSafetyStop(f"Workspace target escapes durable workspace: {target!r}") from exc
            entries.append((target, self._path_identity(candidate)))
        return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @staticmethod
    def _path_identity(path: Path) -> str:
        if not path.exists():
            return "ABSENT"
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return "sha256:" + digest.hexdigest()
        return "DIRECTORY"

    @staticmethod
    def _observed_state(targets: tuple[str, ...], root: Path) -> str:
        if not targets:
            return "PRESENT_COMPLETE"
        states = [_DurableLifecycleBridge._path_identity((root / target).resolve(strict=False)) for target in targets]
        if all(value == "ABSENT" for value in states):
            return "ABSENT"
        if any(value == "ABSENT" for value in states):
            return "PRESENT_PARTIAL"
        return "PRESENT_COMPLETE"

    @staticmethod
    def _evidence_from_row(row: Any) -> WorkspaceEvidence:
        return WorkspaceEvidence(project_id=str(row["project_id"]), run_id=str(row["run_id"]), phase_id=str(row["phase_id"]), task_id=str(row["task_id"]), attempt_id=str(row["attempt_id"]), relative_path=str(row["relative_path"]), change_kind=str(row["change_kind"]), expected_before_identity=row["expected_before_identity"], observed_before_identity=row["observed_before_identity"], expected_after_identity=row["expected_after_identity"], observed_after_identity=row["observed_after_identity"], observed_state=str(row["observed_state"]), checkpoint_id=row["checkpoint_id"], artifact_id=row["artifact_id"], evidence_created_at=str(row["evidence_created_at"]))

class CanonicalOrchestrator:
    """Compose validated AI-Agent boundaries into one canonical flow."""
    def __init__(self, workspace_root: Path, *, understanding: ProjectUnderstandingAdapter, leader: CentralLeader, decomposer: PlanDecomposer, dispatcher: WorkerDispatcher, worker_execution: WorkerExecutionBoundary, worker_adapter: WorkerAdapter, validator_factory: Callable[[ValidationHook], IndependentValidator], authorization: ExecutionAuthorizationBoundary, durable_state: DurableExecutionState | None = None) -> None:
        self.workspace_root = workspace_root.resolve()
        if not self.workspace_root.exists() or not self.workspace_root.is_dir():
            raise OrchestrationSafetyStop(f"Workspace root must be an existing directory: {self.workspace_root}")
        required = {"understanding": understanding, "leader": leader, "decomposer": decomposer, "dispatcher": dispatcher, "worker_execution": worker_execution, "worker_adapter": worker_adapter, "validator_factory": validator_factory, "authorization": authorization}
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise OrchestrationSafetyStop(f"Canonical orchestration requires dependencies: {', '.join(sorted(missing))}")
        if not callable(validator_factory):
            raise OrchestrationSafetyStop("validator_factory must be callable")
        self.understanding = understanding
        self.leader = leader
        self.decomposer = decomposer
        self.dispatcher = dispatcher
        self.worker_execution = worker_execution
        self.worker_adapter = worker_adapter
        self.validator_factory = validator_factory
        self.authorization = authorization
        self._durable = _DurableLifecycleBridge(durable_state, self.workspace_root) if durable_state is not None else None

    def run(self, task_id: str) -> OrchestrationResult:
        if not isinstance(task_id, str) or not task_id.strip():
            raise OrchestrationSafetyStop("Orchestration requires a non-empty task_id")
        understanding: Mapping[str, Any]
        assignments: tuple[WorkerAssignment, ...] = ()
        durable_run_id: str | None = None
        durable_phase_id: str | None = None
        try:
            if self._durable is not None:
                durable_run_id = self._durable.create_run()
            understanding = self.understanding.analyze()
            if not isinstance(understanding, Mapping):
                raise OrchestrationSafetyStop("Project understanding must return a mapping")
            context = understanding.get("context")
            if not isinstance(context, Mapping):
                raise OrchestrationSafetyStop("Project understanding must provide a bounded planning context")
            leader_response = self.leader.plan(task_id, context)
            plan = self.decomposer.decompose(leader_response.payload, context=context)
            if self._durable is not None:
                self._durable.accept_plan(durable_run_id, task_id, plan)
            assignments = tuple(self.dispatcher.assign_plan(plan))
            assignment_by_task = {item.task_id: item for item in assignments}
            tasks = plan.get("tasks")
            if not isinstance(tasks, list) or not tasks:
                raise OrchestrationSafetyStop("Decomposed plan must contain a non-empty task list")
            if self._durable is not None:
                durable_phase_id = f"{durable_run_id}:PHASE:1"
                self._durable.start_phase(durable_run_id, durable_phase_id)
                self._durable.start_running(durable_run_id)
            task_records: list[TaskExecutionRecord] = []
            for task in self._ordered_tasks(tasks):
                current_task_id = task.get("task_id")
                if not isinstance(current_task_id, str) or current_task_id not in assignment_by_task:
                    raise OrchestrationSafetyStop("Plan task has no authoritative worker assignment")
                assignment = assignment_by_task[current_task_id]
                assignment_dict = assignment.to_dict()
                attempt_id: str | None = None
                if self._durable is not None:
                    self._durable.start_task(durable_run_id, durable_phase_id, task)
                    attempt_id = f"{durable_run_id}:{current_task_id}:ATTEMPT:1"
                    self._durable.start_attempt(durable_run_id, durable_phase_id, current_task_id, attempt_id, str(assignment_dict["worker_id"]))
                spec = self.worker_adapter.prepare(task, assignment_dict)
                self._validate_worker_spec(spec, task)
                before_identity = self._durable._workspace_identity(spec.changed_targets) if self._durable is not None else ""
                result = self.worker_execution.execute(assignment_dict, task, command=spec.command, targets=spec.targets, external_reads=spec.external_reads, external_writes=spec.external_writes)
                request = self._request_from_execution(task, assignment_dict, spec)
                durable_artifact_id: str | None = None
                durable_evidence_hash: str | None = None
                durable_checkpoint_sequence: int | None = None
                if self._durable is not None:
                    raw_checkpoint_id = result.checkpoint.get("checkpoint_id") if isinstance(result.checkpoint, Mapping) else None
                    if not isinstance(raw_checkpoint_id, str) or not raw_checkpoint_id.strip():
                        raise OrchestrationSafetyStop("Execution checkpoint_id is required for durable lifecycle")
                    after_identity = self._durable._workspace_identity(spec.changed_targets)
                    _, durable_evidence_hash, durable_artifact_id, durable_checkpoint_sequence = self._durable.persist_post_execution(durable_run_id, durable_phase_id, current_task_id, attempt_id, raw_checkpoint_id, before_identity, after_identity, self._durable._observed_state(spec.changed_targets, self.workspace_root))
                validation_hook: ValidationHook = lambda hook_request, hook_task, hook_result: self.worker_adapter.validate(hook_request, hook_task, hook_result, spec)
                validator = self.validator_factory(validation_hook)
                if not isinstance(validator, IndependentValidator):
                    raise OrchestrationSafetyStop("validator_factory must return IndependentValidator")
                verdict = validator.validate(request, task, result, changed_targets=spec.changed_targets)
                work_product = WorkerWorkProduct.from_validated_execution(task=task, assignment=assignment_dict, request=request, result=result, changes=spec.changes, changed_targets=spec.changed_targets, validation_evidence=verdict.evidence)
                authorization = {"task_id": verdict.task_id, "worker_id": verdict.worker_id, "authorized": bool(spec.changes), "changed_targets": list(spec.changed_targets)}
                if self._durable is not None:
                    validation_id = self._durable.create_and_pass_validation(durable_run_id, durable_phase_id, current_task_id, attempt_id, durable_checkpoint_sequence, durable_evidence_hash, durable_artifact_id)
                else:
                    validation_id = None
                if spec.changes:
                    authorization_result = self.authorization.apply(verdict, checkpoint=result.checkpoint, changes=spec.changes)
                    if not isinstance(authorization_result, Mapping):
                        raise OrchestrationSafetyStop(f"Execution authorization returned invalid result for {current_task_id!r}")
                    transaction_value = authorization_result.get("transaction")
                    if not isinstance(transaction_value, Mapping):
                        raise OrchestrationSafetyStop(f"Execution authorization returned no transaction for {current_task_id!r}")
                    if transaction_value.get("status") != "APPROVED":
                        raise OrchestrationSafetyStop(f"Task {current_task_id!r} did not reach APPROVED state: {transaction_value.get('status')!r}")
                    authorization_value = authorization_result.get("authorization")
                    if isinstance(authorization_value, Mapping):
                        authorization = dict(authorization_value)
                    transaction = dict(transaction_value)
                else:
                    transaction = {"status": "NO_MUTATION", "authorization": authorization}
                if self._durable is not None:
                    self._durable.complete_task(durable_run_id, durable_phase_id, current_task_id, attempt_id, validation_id)
                task_records.append(TaskExecutionRecord(task=dict(task), assignment=assignment_dict, execution_request=request, execution_result=result, validation=verdict, work_product=work_product, authorization=authorization, transaction=transaction))
            if self._durable is not None:
                self._durable.finish(durable_run_id, durable_phase_id)
            return OrchestrationResult(status="APPROVED", task_id=task_id, understanding=dict(understanding), leader_response=leader_response, plan=plan, assignments=assignments, task_records=tuple(task_records), durable_project_id=self._durable.project_id if self._durable else None, durable_run_id=durable_run_id, durable_phase_id=durable_phase_id)
        finally:
            self.dispatcher.release_all(assignments)
            try:
                self.leader.release(task_id)
            except Exception:
                pass

    @staticmethod
    def _ordered_tasks(tasks: list[Any]) -> list[Mapping[str, Any]]:
        by_id: dict[str, Mapping[str, Any]] = {}
        for item in tasks:
            if not isinstance(item, Mapping):
                raise OrchestrationSafetyStop("Every plan task must be an object")
            task_id = item.get("task_id")
            if not isinstance(task_id, str) or not task_id.strip():
                raise OrchestrationSafetyStop("Every plan task requires task_id")
            if task_id in by_id:
                raise OrchestrationSafetyStop(f"Duplicate task_id: {task_id}")
            by_id[task_id] = item
        indegree = {task_id: 0 for task_id in by_id}
        outgoing: dict[str, list[str]] = {task_id: [] for task_id in by_id}
        for task_id, task in by_id.items():
            dependencies = task.get("depends_on", [])
            if not isinstance(dependencies, list):
                raise OrchestrationSafetyStop(f"Task {task_id!r} dependencies must be a list")
            for dependency in dependencies:
                if not isinstance(dependency, str) or dependency not in by_id:
                    raise OrchestrationSafetyStop(f"Task {task_id!r} references unknown dependency {dependency!r}")
                indegree[task_id] += 1
                outgoing[dependency].append(task_id)
        ready = sorted(task_id for task_id, value in indegree.items() if value == 0)
        result: list[Mapping[str, Any]] = []
        while ready:
            current = ready.pop(0)
            result.append(by_id[current])
            for dependent in sorted(outgoing[current]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
                    ready.sort()
        if len(result) != len(by_id):
            raise OrchestrationSafetyStop("Plan dependency graph contains a cycle")
        return result

    @staticmethod
    def _validate_worker_spec(spec: WorkerExecutionSpec, task: Mapping[str, Any]) -> None:
        if not isinstance(spec, WorkerExecutionSpec):
            raise OrchestrationSafetyStop("Worker adapter must return WorkerExecutionSpec")
        if not spec.command:
            raise OrchestrationSafetyStop("Worker execution command must not be empty")
        if spec.changes and {change.path for change in spec.changes} != set(spec.changed_targets):
            raise OrchestrationSafetyStop(f"Worker changes must exactly match changed_targets for {task.get('task_id')!r}")
        if not spec.changes and spec.changed_targets:
            raise OrchestrationSafetyStop("changed_targets cannot be declared without FileChange records")

    def _request_from_execution(self, task: Mapping[str, Any], assignment: Mapping[str, Any], spec: WorkerExecutionSpec) -> ExecutionRequest:
        return ExecutionRequest(task_id=str(task["task_id"]), role=str(task["role"]), worker_id=str(assignment["worker_id"]), workspace_root=str(self.workspace_root), command=tuple(spec.command), targets=tuple(spec.targets), timeout_seconds=self.worker_execution.timeout_seconds, external_reads=tuple(spec.external_reads), external_writes=tuple(spec.external_writes))

def default_validator_factory(workspace_root: Path) -> Callable[[ValidationHook], IndependentValidator]:
    root = workspace_root.resolve()
    def factory(hook: ValidationHook) -> IndependentValidator:
        return IndependentValidator(root, validation_hook=hook)
    return factory

def orchestrate(task_id: str, workspace_root: Path, *, understanding: ProjectUnderstandingAdapter, leader: CentralLeader, decomposer: PlanDecomposer, dispatcher: WorkerDispatcher, worker_execution: WorkerExecutionBoundary, worker_adapter: WorkerAdapter, authorization: ExecutionAuthorizationBoundary, durable_state: DurableExecutionState | None = None) -> OrchestrationResult:
    return CanonicalOrchestrator(workspace_root, understanding=understanding, leader=leader, decomposer=decomposer, dispatcher=dispatcher, worker_execution=worker_execution, worker_adapter=worker_adapter, validator_factory=default_validator_factory(workspace_root), authorization=authorization, durable_state=durable_state).run(task_id)
