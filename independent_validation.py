from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from worker_execution import ExecutionRequest, ExecutionResult, WorkerExecutionSafetyStop


SCHEMA_VERSION = 1


class IndependentValidationError(ValueError):
    """Base error for independent post-execution validation."""


class IndependentValidationSafetyStop(IndependentValidationError):
    """Raised when execution evidence cannot be independently validated."""


@dataclass(frozen=True)
class ValidationVerdict:
    task_id: str
    worker_id: str
    passed: bool
    reasons: tuple[str, ...]
    evidence: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "evidence": dict(self.evidence),
        }


ValidationHook = Callable[
    [ExecutionRequest, Mapping[str, Any], ExecutionResult], Mapping[str, Any]
]


class IndependentValidator:
    """Independent validation boundary after a worker execution.

    The validator never treats a worker's own success flag as sufficient proof.
    It checks identity and checkpoint integrity, rejects incomplete execution
    evidence, and requires an independently-produced validation verdict.
    """

    def __init__(
        self,
        workspace_root: Path,
        *,
        validation_hook: ValidationHook,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        if not self.workspace_root.exists() or not self.workspace_root.is_dir():
            raise IndependentValidationSafetyStop(
                f"Workspace root must be an existing directory: {self.workspace_root}"
            )
        if not callable(validation_hook):
            raise IndependentValidationError("validation_hook must be callable")
        self.validation_hook = validation_hook

    def validate(
        self,
        request: ExecutionRequest,
        task: Mapping[str, Any],
        result: ExecutionResult,
        *,
        changed_targets: Iterable[str] = (),
    ) -> ValidationVerdict:
        self._validate_request(request)
        self._validate_task(task, request)
        self._validate_result(result, request)
        normalized_targets = tuple(
            self._validate_target(target) for target in changed_targets
        )

        evidence = self.validation_hook(request, task, result)
        if not isinstance(evidence, Mapping):
            raise IndependentValidationSafetyStop(
                "Independent validation must return a mapping"
            )
        if evidence.get("passed") is not True:
            reason = self._reason_from_evidence(evidence)
            raise IndependentValidationSafetyStop(
                f"Independent validation failed: {reason}"
            )

        return ValidationVerdict(
            task_id=request.task_id,
            worker_id=request.worker_id,
            passed=True,
            reasons=(),
            evidence={**dict(evidence), "changed_targets": list(normalized_targets)},
        )

    def _validate_request(self, request: ExecutionRequest) -> None:
        if not isinstance(request, ExecutionRequest):
            raise IndependentValidationSafetyStop(
                "Validation requires a WorkerExecution ExecutionRequest"
            )
        if request.workspace_root != str(self.workspace_root):
            raise IndependentValidationSafetyStop(
                "Execution request workspace does not match validator workspace"
            )

    @staticmethod
    def _validate_task(task: Mapping[str, Any], request: ExecutionRequest) -> None:
        if not isinstance(task, Mapping):
            raise IndependentValidationSafetyStop("Validation task must be a mapping")
        if task.get("task_id") != request.task_id:
            raise IndependentValidationSafetyStop(
                "Validation task identity does not match execution request"
            )
        if task.get("role") != request.role:
            raise IndependentValidationSafetyStop(
                "Validation task role does not match execution request"
            )
        acceptance = task.get("acceptance_criteria")
        if not isinstance(acceptance, list) or not acceptance:
            raise IndependentValidationSafetyStop(
                "Validation requires task acceptance criteria"
            )

    @staticmethod
    def _validate_result(result: ExecutionResult, request: ExecutionRequest) -> None:
        if not isinstance(result, ExecutionResult):
            raise IndependentValidationSafetyStop(
                "Validation requires an ExecutionResult"
            )
        checkpoint = result.checkpoint
        if not isinstance(checkpoint, Mapping) or checkpoint.get("isolated") is not True:
            raise IndependentValidationSafetyStop(
                "Execution result lacks an isolated checkpoint attestation"
            )
        if result.timed_out:
            raise IndependentValidationSafetyStop("Timed-out execution cannot be approved")
        if result.truncated:
            raise IndependentValidationSafetyStop(
                "Truncated execution output cannot be independently validated"
            )
        if not result.succeeded or result.returncode != 0:
            raise IndependentValidationSafetyStop(
                f"Worker execution did not succeed for task {request.task_id!r}"
            )

    def _validate_target(self, target: str) -> str:
        if not isinstance(target, str) or not target.strip():
            raise IndependentValidationSafetyStop(
                "Changed targets must be non-empty paths"
            )
        candidate = Path(target)
        resolved = candidate if candidate.is_absolute() else self.workspace_root / candidate
        resolved = resolved.resolve(strict=False)
        try:
            relative = resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise IndependentValidationSafetyStop(
                f"Changed target escapes validator workspace: {target!r}"
            ) from exc

        current = self.workspace_root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise IndependentValidationSafetyStop(
                    f"Symlink/junction changed target is not permitted: {target!r}"
                )
        return relative.as_posix()

    @staticmethod
    def _reason_from_evidence(evidence: Mapping[str, Any]) -> str:
        reason = evidence.get("reason")
        if isinstance(reason, str) and reason.strip():
            return reason.strip()
        return "independent validator did not attest passed=True"


def validate_worker_result(
    workspace_root: Path,
    request: ExecutionRequest,
    task: Mapping[str, Any],
    result: ExecutionResult,
    *,
    validation_hook: ValidationHook,
    changed_targets: Iterable[str] = (),
) -> ValidationVerdict:
    validator = IndependentValidator(
        workspace_root,
        validation_hook=validation_hook,
    )
    return validator.validate(
        request,
        task,
        result,
        changed_targets=changed_targets,
    )
