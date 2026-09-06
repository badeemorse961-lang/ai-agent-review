from __future__ import annotations

from typing import Any, Mapping

from git_mutation_attestation import (
    GitMutationAttestation,
    GitMutationAttestationError,
    attestation_from_dict,
    verify_attestation_binding,
)
from git_mutation_executor import GitMutationResult, GitRepositorySnapshot


class GitMutationResultRestoreError(RuntimeError):
    """Raised when a persisted mutation result cannot be trusted."""


def _require_mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GitMutationResultRestoreError(f"{field} must be a mapping")
    return value


def _require_string(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise GitMutationResultRestoreError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise GitMutationResultRestoreError(f"{field} must be non-empty")
    return value


def _require_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise GitMutationResultRestoreError(f"{field} must be a boolean")
    return value


def _require_string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise GitMutationResultRestoreError(f"{field} must be a list of strings")
    return tuple(value)


def _snapshot_from_dict(value: object, field: str) -> GitRepositorySnapshot:
    payload = _require_mapping(value, field)
    branch = _require_string(payload.get("branch"), f"{field}.branch")
    status_lines = _require_string_list(payload.get("status_lines"), f"{field}.status_lines")
    staged_paths = _require_string_list(payload.get("staged_paths"), f"{field}.staged_paths")
    worktree_paths = _require_string_list(payload.get("worktree_paths"), f"{field}.worktree_paths")
    head_sha = _require_string(
        payload.get("head_sha"),
        f"{field}.head_sha",
        allow_empty=True,
    )
    return GitRepositorySnapshot(
        branch=branch,
        status_lines=status_lines,
        staged_paths=staged_paths,
        worktree_paths=worktree_paths,
        head_sha=head_sha,
    )


def _require_commit_sha(value: object, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    commit_sha = _require_string(value, field)
    if len(commit_sha) not in {40, 64} or any(
        char not in "0123456789abcdefABCDEF" for char in commit_sha
    ):
        raise GitMutationResultRestoreError(f"{field} is not a valid Git object identity")
    return commit_sha


def _require_digest(value: object, field: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    digest = _require_string(value, field)
    if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
        raise GitMutationResultRestoreError(f"{field} is not a SHA-256 digest")
    return digest


def restore_git_mutation_result(value: Mapping[str, Any]) -> GitMutationResult:
    """Strictly restore a persisted GitMutationResult and revalidate its attestation binding."""
    payload = _require_mapping(value, "result")
    if payload.get("schema_version") != 2:
        raise GitMutationResultRestoreError("Unsupported GitMutationResult schema version")

    task_id = _require_string(payload.get("task_id"), "task_id")
    worker_id = _require_string(payload.get("worker_id"), "worker_id")
    targets = _require_string_list(payload.get("targets"), "targets")
    commit_sha = _require_commit_sha(payload.get("commit_sha"), "commit_sha", allow_none=True)
    staged = _require_bool(payload.get("staged"), "staged")
    committed = _require_bool(payload.get("committed"), "committed")
    verified = _require_bool(payload.get("verified"), "verified")
    before = _snapshot_from_dict(payload.get("before"), "before")
    after = _snapshot_from_dict(payload.get("after"), "after")
    commit_message_sha256 = _require_digest(
        payload.get("commit_message_sha256"),
        "commit_message_sha256",
        allow_none=True,
    )

    raw_attestation = payload.get("attestation")
    if raw_attestation is None:
        attestation = None
    else:
        try:
            attestation = attestation_from_dict(_require_mapping(raw_attestation, "attestation"))
        except GitMutationAttestationError as exc:
            raise GitMutationResultRestoreError(str(exc)) from exc

    if verified and committed and not staged:
        raise GitMutationResultRestoreError(
            "A committed verified mutation result must record staged=True"
        )
    if committed and commit_sha is None:
        raise GitMutationResultRestoreError(
            "A committed mutation result requires commit identity"
        )
    if committed and after.head_sha != commit_sha:
        raise GitMutationResultRestoreError(
            "Result post-commit HEAD does not match result commit identity"
        )

    result = GitMutationResult(
        task_id=task_id,
        worker_id=worker_id,
        targets=targets,
        commit_sha=commit_sha,
        staged=staged,
        committed=committed,
        verified=verified,
        before=before,
        after=after,
        commit_message_sha256=commit_message_sha256,
        attestation=attestation,
    )
    verify_restored_attestation(result)
    return result


def verify_restored_attestation(result: GitMutationResult) -> None:
    """Validate the attestation against every authoritative result identity field."""
    if result.attestation is None:
        if result.verified or result.committed:
            raise GitMutationResultRestoreError(
                "A verified or committed mutation result must contain a transaction attestation"
            )
        return

    if result.attestation.task_id != result.task_id:
        raise GitMutationResultRestoreError("Result task identity does not match its attestation")
    if result.attestation.worker_id != result.worker_id:
        raise GitMutationResultRestoreError("Result worker identity does not match its attestation")
    if result.attestation.targets != tuple(sorted(set(result.targets))):
        raise GitMutationResultRestoreError("Result target set does not match its attestation")
    if result.commit_sha != result.attestation.commit_sha:
        raise GitMutationResultRestoreError("Result commit identity does not match its attestation")

    try:
        verify_attestation_binding(
            result.attestation,
            task_id=result.task_id,
            worker_id=result.worker_id,
            workspace=result.attestation_workspace,
            targets=result.targets,
            commit_sha=result.commit_sha or "",
        )
    except AttributeError:
        # Kept unreachable for current GitMutationAttestation; see the explicit workspace check below.
        raise GitMutationResultRestoreError("Attestation workspace binding could not be verified")
    except (GitMutationAttestationError, ValueError) as exc:
        raise GitMutationResultRestoreError(str(exc)) from exc
