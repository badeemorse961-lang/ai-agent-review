from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from central_leader import CentralLeader, LeaderResponse
from execution_authorization import AuthorizationRecord, ExecutionAuthorizationBoundary
from execution_gate import FileChange
from independent_validation import IndependentValidator, ValidationVerdict
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
    """Explicit adapter output describing one worker's proposed work product.

    The spec does not grant execution or mutation authority. The command is
    still checked by ``WorkerExecutionBoundary`` and proposed changes remain
    inert until independent validation and execution authorization accept them.
    """

    command: tuple[str, ...]
    targets: tuple[str, ...]
    checkpoint: Mapping[str, Any]
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
    authorization: AuthorizationRecord
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
                    "authorization": record.authorization.to_dict(),
                    "transaction": dict(record.transaction),
                }
                for record in self.task_records
            ],
        }


class CanonicalOrchestrator:
    """Compose the validated AI-Agent boundaries into one canonical flow.

    This class owns sequencing and cleanup only. It does not implement model
    calls, worker command generation, validation logic, filesystem mutation, or
    Git mutation. Those capabilities remain behind their existing boundaries
    and explicit dependency-injected adapters.

    The production composition is therefore:

        understanding -> CentralLeader -> PlanDecomposer -> WorkerDispatcher
        -> WorkerExecutionBoundary -> IndependentValidator
        -> ExecutionAuthorizationBoundary -> ExecutionGate
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
        validator: IndependentValidator,
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
            "validator": validator,
            "authorization": authorization,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise OrchestrationSafetyStop(
                f"Canonical orchestration requires dependencies: {', '.join(sorted(missing))}"
            )

        self.understanding = understanding
        self.leader = leader
        self.decomposer = decomposer
        self.dispatcher = dispatcher
        self.worker_execution = worker_execution
        self.worker_adapter = worker_adapter
        self.validator = validator
        self.authorization = authorization

    def run(self, task_id: str) -> OrchestrationResult:
        if not isinstance(task_id, str) or not task_id.strip():
            raise OrchestrationSafetyStop("Orchestration requires a non-empty task_id")

        understanding = self.understanding.analyze()
        if not isinstance(understanding, Mapping):
            raise OrchestrationSafetyStop("Project understanding must return a mapping")
        context = understanding.get("context")
        if not isinstance(context, Mapping):
            raise OrchestrationSafetyStop(
                "Project understanding must provide a bounded planning context"
            )

        leader_response = self.leader.plan(task_id, context)
        plan = self.decomposer.decompose(leader_response.payload, context=context)
        assignments = tuple(self.dispatcher.assign_plan(plan))
        assignment_by_task = {item.task_id: item for item in assignments}

        task_records: list[TaskExecutionRecord] = []
        try:
            tasks = plan.get("tasks")
            if not isinstance(tasks, list):
                raise OrchestrationSafetyStop("Decomposed plan is missing tasks")

            for task in self.dispatcher._topological_tasks(tasks):
                if not isinstance(task, Mapping):
                    raise OrchestrationSafetyStop("Plan task is not a mapping")
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

                evidence = self.worker_adapter.validate(
                    self._request_from_execution(task, assignment_dict, spec),
                    task,
                    result,
                    spec,
                )
                if not isinstance(evidence, Mapping):
                    raise OrchestrationSafetyStop(
                        f"Worker validation adapter returned invalid evidence for {current_task_id!r}"
                    )

                validation_hook = lambda request, hook_task, hook_result, evidence=evidence: evidence
                verdict = self.validator.__class__(
                    self.workspace_root,
                    validation_hook=validation_hook,
                ).validate(
                    self._request_from_execution(task, assignment_dict, spec),
                    task,
                    result,
                    changed_targets=spec.targets,
                )

                transaction = self.authorization.apply(
                    verdict,
                    checkpoint=spec.checkpoint,
                    changes=spec.changes,
                )
                record = TaskExecutionRecord(
                    task=dict(task),
                    assignment=assignment_dict,
                    execution_request=self._request_from_execution(task, assignment_dict, spec),
                    execution_result=result,
                    validation=verdict,
                    authorization=self.authorization.authorize(
                        verdict,
                        checkpoint=spec.checkpoint,
                        changes=spec.changes,
                    ),
                    transaction=transaction,
                )
                task_records.append(record)

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

    def _validate_worker_spec(
        self,
        spec: WorkerExecutionSpec,
        task: Mapping[str, Any],
    ) -> None:
        if not isinstance(spec, WorkerExecutionSpec):
            raise OrchestrationSafetyStop("Worker adapter must return WorkerExecutionSpec")
        if not spec.command:
            raise OrchestrationSafetyStop("Worker execution command must not be empty")
        if not isinstance(spec.checkpoint, Mapping) or spec.checkpoint.get("isolated") is not True:
            raise OrchestrationSafetyStop(
                "Worker adapter checkpoint must explicitly attest isolated execution"
            )
        checkpoint_id = spec.checkpoint.get("checkpoint_id")
        if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
            raise OrchestrationSafetyStop(
                "Worker adapter checkpoint requires checkpoint_id"
            )
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise OrchestrationSafetyStop("Plan task requires a non-empty task_id")

        normalized_changes = tuple(change.path for change in spec.changes)
        normalized_targets = tuple(str(path) for path in spec.targets)
        if set(normalized_changes) != set(normalized_targets):
            raise OrchestrationSafetyStop(
                f"Worker changes must exactly match execution targets for {task_id!r}"
            )

    @staticmethod
    def _request_from_execution(
        task: Mapping[str, Any],
        assignment: Mapping[str, Any],
        spec: WorkerExecutionSpec,
    ) -> ExecutionRequest:
        workspace_root = assignment.get("workspace_root")
        if not isinstance(workspace_root, str) or not workspace_root.strip():
            raise OrchestrationSafetyStop("Worker assignment does not identify a workspace")
        return ExecutionRequest(
            task_id=str(task["task_id"]),
            role=str(task["role"]),
            worker_id=str(assignment["worker_id"]),
            workspace_root=workspace_root,
            command=tuple(spec.command),
            targets=tuple(str(item) for item in spec.targets),
            timeout_seconds=120.0,
            external_reads=tuple(spec.external_reads),
            external_writes=tuple(spec.external_writes),
        )


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
    validator: IndependentValidator,
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
        validator=validator,
        authorization=authorization,
    ).run(task_id)
