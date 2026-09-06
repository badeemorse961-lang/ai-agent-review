from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from git_commit_evidence import GitCommitEvidenceError, verify_exact_target_set
from git_mutation_attestation import GitMutationAttestationError, verify_attestation_binding
from git_mutation_executor import GitMutationResult
from git_mutation_result_codec import GitMutationResultRestoreError, verify_restored_attestation
from process_sandbox import ProcessResult, ProcessSandbox


class GitMutationLiveRebindError(RuntimeError):
    """Raised when persisted mutation evidence cannot be rebound to live state."""


@dataclass(frozen=True)
class GitMutationLiveRebindEvidence:
    """Inspection-only evidence proving a restored mutation result still matches live Git."""

    task_id: str
    worker_id: str
    workspace: str
    branch: str
    head_sha: str
    targets: tuple[str, ...]
    commit_evidence_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "workspace": self.workspace,
            "branch": self.branch,
            "head_sha": self.head_sha,
            "targets": list(self.targets),
            "commit_evidence_sha256": self.commit_evidence_sha256,
        }


def rebind_live_git_mutation_result(
    result: GitMutationResult,
    *,
    workspace_root: Path,
    process_sandbox: ProcessSandbox,
) -> GitMutationLiveRebindEvidence:
    """Re-bind a trusted result to the current read-only Git state.

    This function never mutates the repository and never grants authorization.
    It proves that the restored transaction still refers to the active workspace,
    active branch, current HEAD, clean working state, exact committed target set,
    and previously recorded post-commit pathname evidence.
    """

    workspace = workspace_root.resolve()
    if process_sandbox.policy.workspace_root != workspace:
        raise GitMutationLiveRebindError(
            "Live rebind process sandbox must use the active workspace"
        )

    try:
        verify_restored_attestation(result)
    except GitMutationResultRestoreError as exc:
        raise GitMutationLiveRebindError(str(exc)) from exc

    attestation = result.attestation
    if attestation is None:
        raise GitMutationLiveRebindError(
            "Live rebind requires a transaction attestation"
        )
    if not result.committed or not result.verified or not result.commit_sha:
        raise GitMutationLiveRebindError(
            "Live rebind requires a committed and verified mutation result"
        )

    try:
        verify_attestation_binding(
            attestation,
            task_id=result.task_id,
            worker_id=result.worker_id,
            workspace=workspace,
            targets=result.targets,
            commit_sha=result.commit_sha,
        )
    except GitMutationAttestationError as exc:
        raise GitMutationLiveRebindError(str(exc)) from exc

    git_executable = _resolve_git_executable(process_sandbox)
    branch = _run_read_only(
        process_sandbox,
        (git_executable, "branch", "--show-current"),
        "Git live branch resolution",
    ).stdout.strip()
    if not branch:
        raise GitMutationLiveRebindError("Live Git branch could not be proven")
    if branch != result.after.branch:
        raise GitMutationLiveRebindError(
            f"Live branch drifted: expected={result.after.branch!r} actual={branch!r}"
        )

    live_head = _run_read_only(
        process_sandbox,
        (git_executable, "rev-parse", "HEAD"),
        "Git live HEAD resolution",
    ).stdout.strip()
    if live_head != attestation.commit_sha or live_head != result.commit_sha:
        raise GitMutationLiveRebindError(
            "Live HEAD does not match the attested commit identity"
        )

    status = _run_read_only(
        process_sandbox,
        (git_executable, "status", "--porcelain=v1", "-z"),
        "Git live status inspection",
    ).stdout
    if status:
        raise GitMutationLiveRebindError(
            "Live repository is not clean; transaction evidence cannot be rebound"
        )

    show = _run_read_only(
        process_sandbox,
        (git_executable, "show", "--format=", "--name-only", "-z", attestation.commit_sha),
        "Git live commit inspection",
    ).stdout
    try:
        verify_exact_target_set(show, result.targets)
    except GitCommitEvidenceError as exc:
        raise GitMutationLiveRebindError(str(exc)) from exc

    live_commit_evidence_sha256 = hashlib.sha256(show.encode("utf-8")).hexdigest()
    if live_commit_evidence_sha256 != attestation.commit_evidence_sha256:
        raise GitMutationLiveRebindError(
            "Live committed-target evidence digest does not match the attestation"
        )

    return GitMutationLiveRebindEvidence(
        task_id=result.task_id,
        worker_id=result.worker_id,
        workspace=str(workspace),
        branch=branch,
        head_sha=live_head,
        targets=tuple(sorted(_normalize_targets(result.targets))),
        commit_evidence_sha256=live_commit_evidence_sha256,
    )


def _normalize_targets(targets: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(str(target).replace("\\", "/") for target in targets)
    if not normalized or any(not target for target in normalized):
        raise GitMutationLiveRebindError("Live rebind requires non-empty target paths")
    if len(normalized) != len(set(normalized)):
        raise GitMutationLiveRebindError(
            "Live rebind target set contains duplicate paths"
        )
    return normalized


def _resolve_git_executable(process_sandbox: ProcessSandbox) -> str:
    candidates = []
    for path in process_sandbox.policy.allowed_tool_paths:
        name = path.name.lower()
        if name.endswith(".exe"):
            name = name[:-4]
        if name == "git":
            candidates.append(path)
    if not candidates:
        raise GitMutationLiveRebindError(
            "The process sandbox has no explicitly allowlisted Git executable"
        )
    return str(sorted(candidates, key=str)[0])


def _run_read_only(
    process_sandbox: ProcessSandbox,
    command: tuple[str, ...],
    operation: str,
) -> ProcessResult:
    try:
        result = process_sandbox.run(command)
    except Exception as exc:
        raise GitMutationLiveRebindError(
            f"{operation} could not execute under the process sandbox"
        ) from exc
    if result.returncode != 0 or result.timed_out or result.truncated:
        raise GitMutationLiveRebindError(
            f"{operation} did not produce trustworthy live evidence"
        )
    return result
