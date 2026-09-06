from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1


class GitMutationAttestationError(RuntimeError):
    """Raised when transaction-attestation evidence cannot be trusted."""


def _normalize_targets(targets: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(target).replace("\\", "/") for target in targets)
    if not normalized or any(not target for target in normalized):
        raise GitMutationAttestationError("Attestation requires non-empty target paths")
    if len(normalized) != len(set(normalized)):
        raise GitMutationAttestationError("Attestation target set contains duplicate paths")
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class GitMutationAttestation:
    """Immutable binding between a verified Git transaction and its evidence."""

    task_id: str
    worker_id: str
    workspace: str
    targets: tuple[str, ...]
    commit_sha: str
    object_format: str
    staged_evidence_sha256: str
    commit_evidence_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise GitMutationAttestationError("Attestation task_id must be non-empty")
        if not isinstance(self.worker_id, str) or not self.worker_id.strip():
            raise GitMutationAttestationError("Attestation worker_id must be non-empty")
        workspace = str(Path(self.workspace).resolve())
        if workspace != self.workspace:
            raise GitMutationAttestationError("Attestation workspace must be canonical")
        if self.object_format not in {"sha1", "sha256"}:
            raise GitMutationAttestationError("Attestation object format is unsupported")

        expected_lengths = {
            "commit_sha": 40 if self.object_format == "sha1" else 64,
            "staged_evidence_sha256": 64,
            "commit_evidence_sha256": 64,
        }
        for name, expected_length in expected_lengths.items():
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) != expected_length:
                raise GitMutationAttestationError(
                    f"Attestation {name} has invalid hexadecimal length"
                )
            if any(char not in "0123456789abcdefABCDEF" for char in value):
                raise GitMutationAttestationError(
                    f"Attestation {name} must be hexadecimal"
                )

        object.__setattr__(self, "targets", _normalize_targets(self.targets))
        object.__setattr__(self, "workspace", workspace)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "workspace": self.workspace,
            "targets": list(self.targets),
            "commit_sha": self.commit_sha,
            "object_format": self.object_format,
            "staged_evidence_sha256": self.staged_evidence_sha256,
            "commit_evidence_sha256": self.commit_evidence_sha256,
        }


def attestation_from_dict(value: Mapping[str, Any]) -> GitMutationAttestation:
    if not isinstance(value, Mapping):
        raise GitMutationAttestationError("Attestation payload must be a mapping")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise GitMutationAttestationError(
            "Unsupported transaction-attestation schema version"
        )
    targets = value.get("targets")
    if not isinstance(targets, list):
        raise GitMutationAttestationError(
            "Attestation targets must be serialized as a list"
        )
    return GitMutationAttestation(
        task_id=str(value.get("task_id", "")),
        worker_id=str(value.get("worker_id", "")),
        workspace=str(value.get("workspace", "")),
        targets=tuple(str(target) for target in targets),
        commit_sha=str(value.get("commit_sha", "")),
        object_format=str(value.get("object_format", "")),
        staged_evidence_sha256=str(value.get("staged_evidence_sha256", "")),
        commit_evidence_sha256=str(value.get("commit_evidence_sha256", "")),
    )


def verify_attestation_binding(
    attestation: GitMutationAttestation,
    *,
    task_id: str,
    worker_id: str,
    workspace: Path,
    targets: Sequence[str],
    commit_sha: str,
) -> None:
    expected = GitMutationAttestation(
        task_id=task_id,
        worker_id=worker_id,
        workspace=str(workspace.resolve()),
        targets=tuple(targets),
        commit_sha=commit_sha,
        object_format=attestation.object_format,
        staged_evidence_sha256=attestation.staged_evidence_sha256,
        commit_evidence_sha256=attestation.commit_evidence_sha256,
    )
    if attestation != expected:
        raise GitMutationAttestationError(
            "Transaction attestation is not bound to the authorized task, worker, workspace, targets, or commit"
        )
