from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from central_leader import CentralLeader, LeaderResponse
from execution_authorization import ExecutionAuthorizationBoundary
from execution_gate import FileChange
from independent_validation import IndependentValidator, ValidationHook, ValidationVerdict
from plan_decomposer import PlanDecomposer
from worker_dispatch import WorkerAssignment, WorkerDispatcher
from worker_execution import ExecutionRequest, ExecutionResult, WorkerExecutionBoundary


SCHEMA_VERSION = 1


class OrchestrationError(ValueError):
    """Base error raised by the canonical orchestration boundary."""


class OrchestrationSafetyStop(OrchestrationError):
    """Raised when the composed flow cannot proceed safely."""


@dataclass(frozen=True)
class WorkerExecutionSpec:
    """Explicit adapter output for one worker task.

    ``targets`` are execution-scope paths consumed by ``WorkerExecutionBoundary``.
    ``changed_targets`` are the exact paths proposed for mutation. They must
    equal the paths carried by ``changes``. Neither field grants authority.
    """

    command: tuple[str, ...]
    targets: tuple[str, ...]
    changed_targets: tuple[str, ...]
    changes: tuple[FileChange, ...]
    external_reads: tuple[str, ...] = ()
    external_writes: tuple[str, ...] = ()


class ProjectUnderstandingAdapter(Protocol):
    def analyze(self) -> Mapping[str, Any]: ...


class WorkerAdapter(Protocol):
    def prepare(
        self,
        task: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> WorkerExecutionSpec: ...

    def validate(
        self,
        request: ExecutionRequest,
        task: Mapping[str, Any],
        result: ExecutionResult,
        spec: WorkerExecutionSpec,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class TaskExecutionRecord:
    task: Mapping[str, Any]
    assignment: Mapping[str, Any]
    execution_request: ExecutionRequest
    execution_result: ExecutionResult
    validation: ValidationVerdict
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": self.status,
            "task_id": self.task_id,
            "understanding": dict(self.understanding),
            "leader_response": {
                "payload": self.leader_response.payload,
                "account_id": self.leader_response.account_id,
                "model": self.leader_response.model,
                "tier": self.leader_response.tier,
            },
            "plan": dict(self.plan),
            "assignments": [item.to_dict() for item in self.assignments],
            "task_records": [
                {
                    "task": dict(record.task),
                    "assignment": dict(record.assignment),
                    "execution_request": record.execution_request.to_dict(),
                    "execution_result": record.execution_result.to_dict(),
                    "validation": record.validation.to_dict(),
                    "authorization": dict(record.authorization),
                    "transaction": dict(record.transaction),
                }
                for record in self.task_records
            ],
        }


class CanonicalOrchestrator:
    """Compose the validated AI-Agent boundaries into one canonical flow.

    This class owns sequencing and cleanup only. Model calls, worker command
    generation, validation logic, filesystem mutation, and Git mutation remain
    behind existing boundaries or explicit dependency-injected adapters.
    """

    def __init__(
        self,
        workspace_root: Path,
        *,
        understanding: ProjectUnderstandingAdapter,
        leader: CentralLeader,
        decomposer: PlanDecomposer,
        dispatcher: WorkerDispatcher,
        worker_execution: WorkerExecutionBoundary,
        worker_adapter: WorkerAdapter,
        validator_factory: Callable[[ValidationHook], IndependentValidator],
        authorization: ExecutionAuthorizationBoundary,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        if not self.workspace_root.exists() or not self.workspace_root.is_dir():
            raise OrchestrationSafetyStop(
                f"Workspace root must be an existing directory: {self.workspace_root}"
            )

        required = {
            "understanding": understanding,
            "leader": leader,
            "decomposer": decomposer,
            "dispatcher": dispatcher,
            "worker_execution": worker_execution,
            "worker_adapter": worker_adapter,
            "validator_factory": validator_factory,
            "authorization": authorization,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise OrchestrationSafetyStop(
                f"Canonical orchestration requires dependencies: {', '.join(sorted(missing))}"
            )
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

    def run(self, task_id: str) -> OrchestrationResult:
        if not isinstance(task_id, str) or not task_id.strip():
            raise OrchestrationSafetyStop("Orchestration requires a non-empty task_id")

        understanding: Mapping[str, Any]
        assignments: tuple[WorkerAssignment, ...] = ()
        try:
            understanding = self.understanding.analyze()
            if not isinstance(understanding, Mapping):
                raise OrchestrationSafetyStop(
                    "Project understanding must return a mapping"
                )
            context = understanding.get("context")
            if not isinstance(context, Mapping):
                raise OrchestrationSafetyStop(
                    "Project understanding must provide a bounded planning context"
                )

            leader_response = self.leader.plan(task_id, context)
            plan = self.decomposer.decompose(leader_response.payload, context=context)
            assignments = tuple(self.dispatcher.assign_plan(plan))
            assignment_by_task = {item.task_id: item for item in assignments}

            tasks = plan.get("tasks")
            if not isinstance(tasks, list) or not tasks:
                raise OrchestrationSafetyStop("Decomposed plan must contain a non-empty task list")

            task_records: list[TaskExecutionRecord] = []
            for task in self._ordered_tasks(tasks):
                current_task_id = task.get("task_id")
                if not isinstance(current_task_id, str) or current_task_id not in assignment_by_task:
                    raise OrchestrationSafetyStop(
                        "Plan task has no authoritative worker assignment"
                    )

                assignment = assignment_by_task[current_task_id]
                assignment_dict = assignment.to_dict()
                spec = self.worker_adapter.prepare(task, assignment_dict)
                self._validate_worker_spec(spec, task)

                result = self.worker_execution.execute(
                    assignment_dict,
                    task,
                    command=spec.command,
                    targets=spec.targets,
                    external_reads=spec.external_reads,
                    external_writes=spec.external_writes,
                )
                request = self._request_from_execution(task, assignment_dict, spec)

                validation_hook: ValidationHook = (
                    lambda hook_request, hook_task, hook_result: self.worker_adapter.validate(
                        hook_request,
                        hook_task,
                        hook_result,
                        spec,
                    )
                )
                validator = self.validator_factory(validation_hook)
                if not isinstance(validator, IndependentValidator):
                    raise OrchestrationSafetyStop(
                        "validator_factory must return IndependentValidator"
                    )
                verdict = validator.validate(
                    request,
                    task,
                    result,
                    changed_targets=spec.changed_targets,
                )

                authorization = {
                    "task_id": verdict.task_id,
                    "worker_id": verdict.worker_id,
                    "authorized": bool(spec.changes),
                    "changed_targets": list(spec.changed_targets),
                }

                if spec.changes:
                    transaction = self.authorization.apply(
                        verdict,
                        checkpoint=result.checkpoint,
                        changes=spec.changes,
                    )
                    if not isinstance(transaction, Mapping):
                        raise OrchestrationSafetyStop(
                            f"Execution authorization returned invalid transaction for {current_task_id!r}"
                        )
                    if transaction.get("status") != "APPROVED":
                        raise OrchestrationSafetyStop(
                            f"Task {current_task_id!r} did not reach APPROVED state: {transaction.get('status')!r}"
                        )
                else:
                    transaction = {
                        "status": "NO_MUTATION",
                        "authorization": authorization,
                    }

                task_records.append(
                    TaskExecutionRecord(
                        task=dict(task),
                        assignment=assignment_dict,
                        execution_request=request,
                        execution_result=result,
                        validation=verdict,
                        authorization=authorization,
                        transaction=dict(transaction),
                    )
                )

            return OrchestrationResult(
                status="APPROVED",
                task_id=task_id,
                understanding=dict(understanding),
                leader_response=leader_response,
                plan=plan,
                assignments=assignments,
                task_records=tuple(task_records),
            )
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
                raise OrchestrationSafetyStop(
                    f"Task {task_id!r} dependencies must be a list"
                )
            for dependency in dependencies:
                if not isinstance(dependency, str) or dependency not in by_id:
                    raise OrchestrationSafetyStop(
                        f"Task {task_id!r} references unknown dependency {dependency!r}"
                    )
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
    def _validate_worker_spec(
        spec: WorkerExecutionSpec,
        task: Mapping[str, Any],
    ) -> None:
        if not isinstance(spec, WorkerExecutionSpec):
            raise OrchestrationSafetyStop(
                "Worker adapter must return WorkerExecutionSpec"
            )
        if not spec.command:
            raise OrchestrationSafetyStop("Worker execution command must not be empty")
        if not isinstance(spec.targets, tuple) or not isinstance(spec.changed_targets, tuple):
            raise OrchestrationSafetyStop("Worker execution paths must use normalized tuples")
        if not spec.changes and spec.changed_targets:
            raise OrchestrationSafetyStop(
                "changed_targets cannot be declared without FileChange records"
            )
        change_paths = {change.path for change in spec.changes}
        if change_paths != set(spec.changed_targets):
            raise OrchestrationSafetyStop(
                f"Worker changes must exactly match changed_targets for {task.get('task_id')!r}"
            )
        for change in spec.changes:
            if not isinstance(change, FileChange):
                raise OrchestrationSafetyStop("Worker changes must use FileChange records")

    def _request_from_execution(
        self,
        task: Mapping[str, Any],
        assignment: Mapping[str, Any],
        spec: WorkerExecutionSpec,
    ) -> ExecutionRequest:
        return ExecutionRequest(
            task_id=str(task["task_id"]),
            role=str(task["role"]),
            worker_id=str(assignment["worker_id"]),
            workspace_root=str(self.workspace_root),
            command=tuple(spec.command),
            targets=tuple(spec.targets),
            timeout_seconds=self.worker_execution.timeout_seconds,
            external_reads=tuple(spec.external_reads),
            external_writes=tuple(spec.external_writes),
        )


def default_validator_factory(
    workspace_root: Path,
) -> Callable[[ValidationHook], IndependentValidator]:
    """Create per-task independent validators with a caller-supplied hook."""
    root = workspace_root.resolve()

    def factory(hook: ValidationHook) -> IndependentValidator:
        return IndependentValidator(root, validation_hook=hook)

    return factory


def orchestrate(
    task_id: str,
    workspace_root: Path,
    *,
    understanding: ProjectUnderstandingAdapter,
    leader: CentralLeader,
    decomposer: PlanDecomposer,
    dispatcher: WorkerDispatcher,
    worker_execution: WorkerExecutionBoundary,
    worker_adapter: WorkerAdapter,
    authorization: ExecutionAuthorizationBoundary,
) -> OrchestrationResult:
    """Functional entry point for the canonical orchestration composition."""
    return CanonicalOrchestrator(
        workspace_root,
        understanding=understanding,
        leader=leader,
        decomposer=decomposer,
        dispatcher=dispatcher,
        worker_execution=worker_execution,
        worker_adapter=worker_adapter,
        validator_factory=default_validator_factory(workspace_root),
        authorization=authorization,
    ).run(task_id)
