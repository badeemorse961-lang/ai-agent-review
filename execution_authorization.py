from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from execution_gate import ExecutionGate, FileChange
from independent_validation import ValidationVerdict

SCHEMA_VERSION = 2


class ExecutionAuthorizationError(ValueError):
    """Base error for final authorization failures."""


class ExecutionAuthorizationSafetyStop(ExecutionAuthorizationError):
    """Raised when a validated task cannot be safely promoted to mutation."""


@dataclass(frozen=True)
class AuthorizationRecord:
    """Auditable internal authorization decision; not a human prompt."""

    task_id: str
    worker_id: str
    authorized: bool
    changed_targets: tuple[str, ...]
    basis: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "authorized": self.authorized,
            "changed_targets": list(self.changed_targets),
            "basis": list(self.basis),
        }


class ExecutionAuthorizationBoundary:
    """Bridge independent validation into the repository's existing gate.

    Authorization is an internal policy decision, not a request for human
    confirmation on every step. Once the validated safety prerequisites agree,
    the boundary creates an auditable authorization record and delegates the
    actual mutation transaction to the existing ExecutionGate.
    """

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self.gate = ExecutionGate(self.workspace_root)

    def authorize(
        self,
        verdict: ValidationVerdict,
        *,
        checkpoint: Mapping[str, Any],
        changes: Sequence[FileChange],
    ) -> AuthorizationRecord:
        if not isinstance(verdict, ValidationVerdict) or verdict.passed is not True:
            raise ExecutionAuthorizationSafetyStop(
                "Mutation requires a passed independent validation verdict"
            )

        if not isinstance(verdict.task_id, str) or not verdict.task_id.strip():
            raise ExecutionAuthorizationSafetyStop(
                "Validation verdict requires a non-empty task identity"
            )
        if not isinstance(verdict.worker_id, str) or not verdict.worker_id.strip():
            raise ExecutionAuthorizationSafetyStop(
                "Validation verdict requires a non-empty worker identity"
            )

        evidence = verdict.evidence
        if not isinstance(evidence, Mapping):
            raise ExecutionAuthorizationSafetyStop(
                "Validation verdict evidence must be a mapping"
            )
        if evidence.get("passed") is not True:
            raise ExecutionAuthorizationSafetyStop(
                "Validation evidence must explicitly attest passed=True"
            )

        evidence_task_id = evidence.get("task_id")
        if evidence_task_id is not None and evidence_task_id != verdict.task_id:
            raise ExecutionAuthorizationSafetyStop(
                "Validation evidence task identity does not match the verdict"
            )
        evidence_worker_id = evidence.get("worker_id")
        if evidence_worker_id is not None and evidence_worker_id != verdict.worker_id:
            raise ExecutionAuthorizationSafetyStop(
                "Validation evidence worker identity does not match the verdict"
            )

        if not isinstance(checkpoint, Mapping) or checkpoint.get("isolated") is not True:
            raise ExecutionAuthorizationSafetyStop(
                "Mutation requires an isolated checkpoint attestation"
            )

        checkpoint_id = checkpoint.get("checkpoint_id")
        evidence_checkpoint_id = evidence.get("checkpoint_id")
        legacy_checkpoint_binding = False
        if not isinstance(checkpoint_id, str) or not checkpoint_id.strip():
            transaction_id = checkpoint.get("transaction_id")
            if (
                isinstance(transaction_id, str)
                and transaction_id.strip()
                and transaction_id.strip() == verdict.task_id.strip()
                and evidence.get("validated") is True
            ):
                checkpoint_id = transaction_id
                legacy_checkpoint_binding = True
            else:
                raise ExecutionAuthorizationSafetyStop(
                    "Mutation checkpoint requires a non-empty checkpoint_id"
                )
        if not isinstance(evidence_checkpoint_id, str) or not evidence_checkpoint_id.strip():
            if legacy_checkpoint_binding:
                evidence_checkpoint_id = checkpoint_id
            else:
                raise ExecutionAuthorizationSafetyStop(
                    "Validation evidence requires the execution checkpoint_id"
                )
        if evidence_checkpoint_id.strip() != checkpoint_id.strip():
            raise ExecutionAuthorizationSafetyStop(
                "Validation evidence checkpoint does not match the authorized checkpoint"
            )

        target_evidence = evidence.get("changed_targets")
        if not isinstance(target_evidence, list):
            raise ExecutionAuthorizationSafetyStop(
                "Validation evidence must contain changed_targets"
            )

        change_paths = tuple(self._normalize_change_path(change) for change in changes)
        evidence_paths = tuple(
            self._normalize_evidence_path(path) for path in target_evidence
        )
        if set(change_paths) != set(evidence_paths):
            raise ExecutionAuthorizationSafetyStop(
                "Authorized mutation targets do not exactly match independently validated targets"
            )

        basis = [
            "independent_validation_passed",
            "validation_evidence_explicitly_passed",
            "validation_identity_consistent",
            "validation_checkpoint_bound",
            "isolated_checkpoint_attested",
            "mutation_targets_exactly_match_validation_targets",
        ]
        if legacy_checkpoint_binding:
            basis.append("legacy_transaction_id_checkpoint_compatibility")

        return AuthorizationRecord(
            task_id=verdict.task_id,
            worker_id=verdict.worker_id,
            authorized=True,
            changed_targets=change_paths,
            basis=tuple(basis),
        )

    def apply(
        self,
        verdict: ValidationVerdict,
        *,
        checkpoint: Mapping[str, Any],
        changes: Sequence[FileChange],
    ) -> dict[str, Any]:
        record = self.authorize(
            verdict,
            checkpoint=checkpoint,
            changes=changes,
        )
        transaction = self.gate.execute(changes)
        return {
            "schema_version": SCHEMA_VERSION,
            "authorization": record.to_dict(),
            "transaction": transaction,
        }

    def rollback(self, checkpoint_path: Path) -> None:
        self.gate.rollback(checkpoint_path)

    def _normalize_change_path(self, change: FileChange) -> str:
        if not isinstance(change, FileChange):
            raise ExecutionAuthorizationSafetyStop(
                "All mutation proposals must use ExecutionGate FileChange records"
            )
        return self._normalize_relative_path(change.path)

    @staticmethod
    def _normalize_evidence_path(path: Any) -> str:
        if not isinstance(path, str) or not path.strip():
            raise ExecutionAuthorizationSafetyStop(
                "Validated target paths must be non-empty strings"
            )
        return ExecutionAuthorizationBoundary._normalize_relative_path(path)

    @staticmethod
    def _normalize_relative_path(path: str) -> str:
        candidate = Path(path)
        if (
            candidate.is_absolute()
            or candidate.drive
            or candidate.root
            or not path.strip()
        ):
            raise ExecutionAuthorizationSafetyStop(
                f"Mutation target must be a relative workspace path: {path!r}"
            )
        if any(part in {"", ".", ".."} for part in candidate.parts):
            raise ExecutionAuthorizationSafetyStop(
                f"Unsafe mutation target: {path!r}"
            )
        return candidate.as_posix()


def authorize_and_apply(
    workspace_root: Path,
    verdict: ValidationVerdict,
    *,
    checkpoint: Mapping[str, Any],
    changes: Sequence[FileChange],
) -> dict[str, Any]:
    return ExecutionAuthorizationBoundary(workspace_root).apply(
        verdict,
        checkpoint=checkpoint,
        changes=changes,
    )
