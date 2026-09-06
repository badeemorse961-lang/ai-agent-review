from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from execution_authorization import ExecutionAuthorizationBoundary
from execution_gate import FileChange
from independent_validation import ValidationVerdict
from git_mutation_policy import (
    GitMutationPolicy,
    GitMutationRequest,
    GitMutationSafetyStop,
)
from process_sandbox import ProcessResult, ProcessSandbox, ProcessSandboxSafetyStop


SCHEMA_VERSION = 2


class GitMutationExecutorError(RuntimeError):
    """Base error for controlled Git mutation failures."""


class GitMutationVerificationError(GitMutationExecutorError):
    """Raised when post-mutation repository evidence is not task-scoped."""


@dataclass(frozen=True)
class GitRepositorySnapshot:
    """Minimal repository state captured around a mutation transaction."""

    branch: str
    status_lines: tuple[str, ...]
    staged_paths: tuple[str, ...]
    worktree_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "branch": self.branch,
            "status_lines": list(self.status_lines),
            "staged_paths": list(self.staged_paths),
            "worktree_paths": list(self.worktree_paths),
        }


@dataclass(frozen=True)
class GitMutationResult:
    task_id: str
    worker_id: str
    targets: tuple[str, ...]
    commit_sha: str | None
    staged: bool
    committed: bool
    verified: bool
    before: GitRepositorySnapshot
    after: GitRepositorySnapshot
    commit_message_sha256: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "targets": list(self.targets),
            "commit_sha": self.commit_sha,
            "staged": self.staged,
            "committed": self.committed,
            "verified": self.verified,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "commit_message_sha256": self.commit_message_sha256,
        }


class _WorkspaceMutationLock:
    """Cross-process exclusive lock keyed to one workspace."""

    def __init__(self, workspace_root: Path) -> None:
        digest = hashlib.sha256(
            str(workspace_root.resolve()).encode("utf-8")
        ).hexdigest()[:24]
        self.path = (
            Path(tempfile.gettempdir())
            / f"ai-agent-git-mutation-{digest}.lock"
        )
        self._handle: int | None = None

    def __enter__(self) -> "_WorkspaceMutationLock":
        try:
            self._handle = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
            os.write(self._handle, str(os.getpid()).encode("ascii"))
        except FileExistsError as exc:
            raise GitMutationSafetyStop(
                "Another task-scoped Git mutation is already active for this workspace"
            ) from exc
        except OSError as exc:
            raise GitMutationSafetyStop(
                f"Unable to acquire the Git mutation lock: {exc}"
            ) from exc
        return self

    def __exit__(self, *_: object) -> None:
        if self._handle is not None:
            try:
                os.close(self._handle)
            finally:
                self._handle = None
                try:
                    self.path.unlink(missing_ok=True)
                except OSError:
                    pass


class GitMutationExecutor:
    """Perform only local Git mutations bound to one validated task.

    This is intentionally separate from TerminalExecutor/GitSafetyPolicy.
    Ordinary terminal Git access remains inspection-only. This control plane
    adds exactly two mutation capabilities: stage validated targets and commit
    the exact staged target set. Remote operations and history rewriting are
    not available.

    The public transaction path additionally requires the repository's existing
    independent-validation and internal authorization evidence. A caller cannot
    turn the Git mutation layer into an independent source of authority.
    """

    def __init__(
        self,
        workspace_root: Path,
        *,
        process_sandbox: ProcessSandbox,
        policy: GitMutationPolicy | None = None,
        audit_path: Path | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        if process_sandbox.policy.workspace_root != self.workspace_root:
            raise GitMutationSafetyStop(
                "Git mutation process sandbox must use the active workspace"
            )
        self.process_sandbox = process_sandbox
        self.policy = policy or GitMutationPolicy()
        self.git_executable = self._resolve_git_executable()
        self.audit_path = (
            audit_path.resolve()
            if audit_path is not None
            else self.workspace_root
            / ".agent_runtime"
            / "git_mutation_state.json"
        )

    def execute(
        self,
        *,
        verdict: ValidationVerdict,
        checkpoint: Mapping[str, Any],
        changes: Sequence[FileChange],
        commit_message: str,
    ) -> GitMutationResult:
        authorization = ExecutionAuthorizationBoundary(self.workspace_root).authorize(
            verdict,
            checkpoint=checkpoint,
            changes=changes,
        )
        targets = authorization.changed_targets
        if not targets:
            raise GitMutationSafetyStop("Authorized Git mutation requires at least one target")

        stage_request = self.policy.validate_request(
            task_id=authorization.task_id,
            worker_id=authorization.worker_id,
            operation="stage",
            targets=targets,
            workspace_root=self.workspace_root,
        )
        commit_request = self.policy.validate_request(
            task_id=authorization.task_id,
            worker_id=authorization.worker_id,
            operation="commit",
            targets=stage_request.targets,
            commit_message=commit_message,
            workspace_root=self.workspace_root,
        )

        with _WorkspaceMutationLock(self.workspace_root):
            before = self.snapshot()
            self._preflight(before, stage_request.targets)

            self._run_policy_command(stage_request)
            staged = self.snapshot()
            self._verify_staged_targets(staged, stage_request.targets)

            try:
                commit_process = self._run_policy_command(commit_request)
            except (ProcessSandboxSafetyStop, GitMutationSafetyStop) as exc:
                raise GitMutationExecutorError(
                    "Git commit did not complete; staged task changes were left untouched for evidence-preserving recovery"
                ) from exc

            if commit_process.returncode != 0 or commit_process.timed_out:
                raise GitMutationExecutorError(
                    "Git commit failed; staged task changes were left untouched for evidence-preserving recovery"
                )

            after = self.snapshot()
            commit_sha = self._resolve_head_sha()
            self._verify_post_commit(
                after,
                commit_sha,
                commit_request.targets,
                before,
            )

            result = GitMutationResult(
                task_id=stage_request.task_id,
                worker_id=stage_request.worker_id,
                targets=stage_request.targets,
                commit_sha=commit_sha,
                staged=True,
                committed=True,
                verified=True,
                before=before,
                after=after,
                commit_message_sha256=hashlib.sha256(
                    commit_request.commit_message.encode("utf-8")
                ).hexdigest(),
            )
            self._persist_audit(result)
            return result

    def snapshot(self) -> GitRepositorySnapshot:
        status_result = self._run_internal(
            [self.git_executable, "status", "--porcelain=v1", "--branch"]
        )
        self._require_success(status_result, "Git status")
        branch = self._parse_branch(status_result.stdout)
        lines = tuple(
            line
            for line in status_result.stdout.splitlines()
            if line and not line.startswith("##")
        )
        staged_paths: list[str] = []
        worktree_paths: list[str] = []
        for line in lines:
            if len(line) < 3:
                raise GitMutationVerificationError(
                    f"Unparseable Git status evidence: {line!r}"
                )
            index_code = line[0]
            worktree_code = line[1]
            path_text = line[3:]
            if " -> " in path_text:
                old_path, new_path = path_text.split(" -> ", 1)
                paths = (
                    self._normalize_status_path(old_path),
                    self._normalize_status_path(new_path),
                )
            else:
                paths = (self._normalize_status_path(path_text),)
            if index_code != " ":
                staged_paths.extend(paths)
            if worktree_code != " ":
                worktree_paths.extend(paths)
        return GitRepositorySnapshot(
            branch=branch,
            status_lines=lines,
            staged_paths=tuple(sorted(set(staged_paths))),
            worktree_paths=tuple(sorted(set(worktree_paths))),
        )

    def _preflight(self, before: GitRepositorySnapshot, targets: Sequence[str]) -> None:
        expected = set(targets)
        if before.staged_paths:
            raise GitMutationSafetyStop(
                "Preflight requires an empty Git index; existing staged changes could belong to another transaction"
            )
        unexpected = set(before.worktree_paths) - expected
        if unexpected:
            raise GitMutationSafetyStop(
                f"Preflight found unrelated working-tree changes: {sorted(unexpected)}"
            )
        if not set(before.worktree_paths).issubset(expected):
            raise GitMutationSafetyStop("Working-tree state cannot be proven task-scoped")

    def _run_policy_command(self, request: GitMutationRequest) -> ProcessResult:
        command = self.policy.command(request)
        validated = self.policy.validate_command(
            command,
            request=request,
            workspace_root=self.workspace_root,
        )
        executable_command = (self.git_executable, *validated[1:])
        return self.process_sandbox.run(
            executable_command,
            target_paths=request.targets,
        )

    def _run_internal(self, command: Sequence[str]) -> ProcessResult:
        if not command:
            raise GitMutationVerificationError("Internal Git command is empty")
        executable_command = (self.git_executable, *tuple(command[1:]))
        return self.process_sandbox.run(executable_command)

    def _verify_staged_targets(
        self,
        snapshot: GitRepositorySnapshot,
        targets: Sequence[str],
    ) -> None:
        expected = set(targets)
        staged = set(snapshot.staged_paths)
        if staged != expected:
            raise GitMutationVerificationError(
                f"Staged target set mismatch: expected={sorted(expected)!r} actual={sorted(staged)!r}"
            )

    def _resolve_head_sha(self) -> str:
        result = self._run_internal(
            [self.git_executable, "rev-parse", "HEAD"]
        )
        self._require_success(result, "Git HEAD resolution")
        sha = result.stdout.strip()
        if len(sha) < 7 or any(
            char not in "0123456789abcdefABCDEF" for char in sha
        ):
            raise GitMutationVerificationError(
                "Post-commit HEAD is not a valid Git SHA"
            )
        return sha

    def _verify_post_commit(
        self,
        after: GitRepositorySnapshot,
        commit_sha: str,
        targets: Sequence[str],
        before: GitRepositorySnapshot,
    ) -> None:
        if after.staged_paths:
            raise GitMutationVerificationError(
                "Post-commit index is not clean; commit scope cannot be proven"
            )
        if after.worktree_paths:
            raise GitMutationVerificationError(
                "Post-commit working tree is not clean; mutation verification is incomplete"
            )
        if before.staged_paths:
            raise GitMutationVerificationError(
                "Preflight staged state unexpectedly changed"
            )

        show = self._run_internal(
            [self.git_executable, "show", "--format=", "--name-only", commit_sha]
        )
        self._require_success(show, "Git commit inspection")
        touched = {
            self._normalize_status_path(line)
            for line in show.stdout.splitlines()
            if line.strip()
        }
        expected = set(targets)
        if touched != expected:
            raise GitMutationVerificationError(
                f"Committed target set mismatch: expected={sorted(expected)!r} actual={sorted(touched)!r}"
            )

    def _persist_audit(self, result: GitMutationResult) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.audit_path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp.replace(self.audit_path)

    def _resolve_git_executable(self) -> str:
        candidates = []
        for path in self.process_sandbox.policy.allowed_tool_paths:
            name = path.name.lower()
            if name.endswith(".exe"):
                name = name[:-4]
            if name == "git":
                candidates.append(path)
        if not candidates:
            raise GitMutationSafetyStop(
                "The process sandbox has no explicitly allowlisted Git executable"
            )
        return str(sorted(candidates, key=str)[0])

    @staticmethod
    def _normalize_status_path(value: str) -> str:
        return value.strip().replace("\\", "/")

    @staticmethod
    def _parse_branch(status_output: str) -> str:
        for line in status_output.splitlines():
            if line.startswith("##"):
                value = line[2:].strip()
                if "..." in value:
                    value = value.split("...", 1)[0]
                return value
        raise GitMutationVerificationError(
            "Git status did not report the active branch"
        )

    @staticmethod
    def _require_success(result: ProcessResult, operation: str) -> None:
        if result.returncode != 0 or result.timed_out or result.truncated:
            raise GitMutationVerificationError(
                f"{operation} did not produce trustworthy evidence"
            )


def mutate_repository(
    workspace_root: Path,
    *,
    process_sandbox: ProcessSandbox,
    verdict: ValidationVerdict,
    checkpoint: Mapping[str, Any],
    changes: Sequence[FileChange],
    commit_message: str,
    policy: GitMutationPolicy | None = None,
) -> GitMutationResult:
    return GitMutationExecutor(
        workspace_root,
        process_sandbox=process_sandbox,
        policy=policy,
    ).execute(
        verdict=verdict,
        checkpoint=checkpoint,
        changes=changes,
        commit_message=commit_message,
    )
