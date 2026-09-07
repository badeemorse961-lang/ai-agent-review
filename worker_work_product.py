from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from execution_gate import FileChange
from worker_execution import ExecutionRequest, ExecutionResult


SCHEMA_VERSION = 1


class WorkerWorkProductError(ValueError):
    """Raised when a worker work product cannot satisfy its authority contract."""


@dataclass(frozen=True)
class WorkerWorkProductFailure:
    """Safe, bounded failure metadata for an authoritative work product."""

    code: str
    message: str
    returncode: int
    timed_out: bool
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class WorkerWorkProduct:
    """Authoritative, typed worker output after independent validation.

    The worker proposes command/target/change data through the existing
    ``WorkerExecutionSpec``. This object is created only after the Core has
    bound that proposal to the authoritative task/worker identity, execution
    result, checkpoint, and independent validation evidence.

    Raw stdout/stderr are deliberately excluded. Failure metadata is bounded
    and suitable for observable evidence; callers must use the central
    redaction boundary for any richer diagnostics.
    """

    task_id: str
    worker_id: str
    command: tuple[str, ...]
    execution_targets: tuple[str, ...]
    changed_targets: tuple[str, ...]
    changes: tuple[FileChange, ...]
    required_validation: tuple[str, ...]
    validation_evidence: Mapping[str, Any]
    execution_result: Mapping[str, Any]
    status: str
    failure: WorkerWorkProductFailure | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "command": list(self.command),
            "execution_targets": list(self.execution_targets),
            "changed_targets": list(self.changed_targets),
            "changes": [
                {
                    "path": change.path,
                    "old_text": change.old_text,
                    "new_text": change.new_text,
                }
                for change in self.changes
            ],
            "required_validation": list(self.required_validation),
            "validation_evidence": dict(self.validation_evidence),
            "execution_result": dict(self.execution_result),
            "status": self.status,
            "failure": self.failure.to_dict() if self.failure else None,
        }

    @classmethod
    def from_validated_execution(
        cls,
        *,
        task: Mapping[str, Any],
        assignment: Mapping[str, Any],
        request: ExecutionRequest,
        result: ExecutionResult,
        changes: tuple[FileChange, ...],
        changed_targets: tuple[str, ...],
        validation_evidence: Mapping[str, Any],
    ) -> "WorkerWorkProduct":
        task_id = _required_identity(task.get("task_id"), "task.task_id")
        worker_id = _required_identity(assignment.get("worker_id"), "assignment.worker_id")
        request_task_id = _required_identity(request.task_id, "request.task_id")
        request_worker_id = _required_identity(request.worker_id, "request.worker_id")
        if task_id != request_task_id:
            raise WorkerWorkProductError("Task identity does not match execution request")
        if worker_id != request_worker_id:
            raise WorkerWorkProductError("Worker identity does not match execution request")

        required_validation = _required_text_list(
            task.get("acceptance_criteria"),
            "task.acceptance_criteria",
        )
        evidence = _validate_validation_evidence(validation_evidence, result)
        normalized_changed_targets = tuple(_normalize_target(value, request.workspace_root) for value in changed_targets)
        normalized_changes = tuple(changes)
        normalized_change_targets = tuple(
            _normalize_target(change.path, request.workspace_root)
            for change in normalized_changes
        )
        if set(normalized_changed_targets) != set(normalized_change_targets):
            raise WorkerWorkProductError(
                "changed_targets must exactly match FileChange.path values"
            )

        execution_result = _execution_summary(result)
        return cls(
            task_id=task_id,
            worker_id=worker_id,
            command=tuple(request.command),
            execution_targets=tuple(request.targets),
            changed_targets=normalized_changed_targets,
            changes=normalized_changes,
            required_validation=required_validation,
            validation_evidence=evidence,
            execution_result=execution_result,
            status="SUCCEEDED",
            failure=None,
        )

    @classmethod
    def from_failed_execution(
        cls,
        *,
        task: Mapping[str, Any],
        assignment: Mapping[str, Any],
        request: ExecutionRequest,
        result: ExecutionResult,
        changes: tuple[FileChange, ...] = (),
        changed_targets: tuple[str, ...] = (),
        reason: str = "worker execution did not complete successfully",
    ) -> "WorkerWorkProduct":
        task_id = _required_identity(task.get("task_id"), "task.task_id")
        worker_id = _required_identity(assignment.get("worker_id"), "assignment.worker_id")
        if task_id != request.task_id:
            raise WorkerWorkProductError("Task identity does not match execution request")
        if worker_id != request.worker_id:
            raise WorkerWorkProductError("Worker identity does not match execution request")
        required_validation = _required_text_list(
            task.get("acceptance_criteria"),
            "task.acceptance_criteria",
        )
        normalized_changed_targets = tuple(_normalize_target(value, request.workspace_root) for value in changed_targets)
        normalized_changes = tuple(changes)
        if set(normalized_changed_targets) != {
            _normalize_target(change.path, request.workspace_root) for change in normalized_changes
        }:
            raise WorkerWorkProductError(
                "changed_targets must exactly match FileChange.path values"
            )

        timed_out_or_truncated = result.timed_out or result.truncated
        status = "SAFE_STOP" if timed_out_or_truncated else "FAILED"
        code = "EXECUTION_SAFE_STOP" if timed_out_or_truncated else "EXECUTION_FAILED"
        bounded_reason = reason.strip() if isinstance(reason, str) and reason.strip() else code
        failure = WorkerWorkProductFailure(
            code=code,
            message=bounded_reason[:256],
            returncode=int(result.returncode),
            timed_out=bool(result.timed_out),
            truncated=bool(result.truncated),
        )
        return cls(
            task_id=task_id,
            worker_id=worker_id,
            command=tuple(request.command),
            execution_targets=tuple(request.targets),
            changed_targets=normalized_changed_targets,
            changes=normalized_changes,
            required_validation=required_validation,
            validation_evidence={},
            execution_result=_execution_summary(result),
            status=status,
            failure=failure,
        )


def _required_identity(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkerWorkProductError(f"{field} must be a non-empty string")
    return value.strip()


def _required_text_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise WorkerWorkProductError(f"{field} must be a non-empty list")
    normalized = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise WorkerWorkProductError(f"{field} contains an empty/non-string value")
        normalized.append(item.strip())
    return tuple(dict.fromkeys(normalized))


def _normalize_target(value: Any, workspace_root: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkerWorkProductError("Work-product targets must be non-empty strings")
    root = Path(workspace_root).resolve()
    candidate = Path(value)
    resolved = candidate if candidate.is_absolute() else root / candidate
    resolved = resolved.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise WorkerWorkProductError(
            f"Work-product target escapes workspace: {value!r}"
        ) from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise WorkerWorkProductError(
                f"Symlink/junction work-product target is not permitted: {value!r}"
            )
    return relative.as_posix()


def _validate_validation_evidence(
    evidence: Mapping[str, Any],
    result: ExecutionResult,
) -> Mapping[str, Any]:
    if not isinstance(evidence, Mapping):
        raise WorkerWorkProductError("Validation evidence must be a mapping")
    if evidence.get("passed") is not True:
        raise WorkerWorkProductError("Authoritative work product requires passed=True validation evidence")
    checkpoint = result.checkpoint
    checkpoint_id = checkpoint.get("checkpoint_id") if isinstance(checkpoint, Mapping) else None
    if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
        raise WorkerWorkProductError("Execution result requires a checkpoint_id")
    evidence_checkpoint = evidence.get("checkpoint_id")
    if evidence_checkpoint is not None and evidence_checkpoint != checkpoint_id:
        raise WorkerWorkProductError(
            "Validation evidence checkpoint_id does not match execution checkpoint"
        )
    normalized = dict(evidence)
    normalized["checkpoint_id"] = checkpoint_id
    return normalized


def _execution_summary(result: ExecutionResult) -> dict[str, Any]:
    checkpoint = result.checkpoint
    checkpoint_id = checkpoint.get("checkpoint_id") if isinstance(checkpoint, Mapping) else None
    return {
        "returncode": int(result.returncode),
        "succeeded": bool(result.succeeded),
        "timed_out": bool(result.timed_out),
        "truncated": bool(result.truncated),
        "checkpoint_id": checkpoint_id,
    }
