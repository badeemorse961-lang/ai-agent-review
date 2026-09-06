from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from execution_authorization import ExecutionAuthorizationBoundary
from execution_gate import FileChange
from git_commit_evidence import GitCommitEvidenceError, verify_exact_target_set
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
    head_sha: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "branch": self.branch,
            "status_lines": list(self.status_lines),
            "staged_paths": list(self.staged_paths),
            "worktree_paths": list(self.worktree_paths),
            "head_sha": self.head_sha,
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
        for _ in range(2):
            try:
                self._handle = os.open(
                    self.path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                os.write(self._handle, str(os.getpid()).encode("ascii"))
                return self
            except FileExistsError as exc:
                if not self._reclaim_stale_lock():
                    raise GitMutationSafetyStop(
                        "Another task-scoped Git mutation is already active for this workspace"
                    ) from exc
            except OSError as exc:
                raise GitMutationSafetyStop(
                    f"Unable to acquire the Git mutation lock: {exc}"
                ) from exc
        raise GitMutationSafetyStop("Unable to acquire the Git mutation lock safely")

    def _reclaim_stale_lock(self) -> bool:
        try:
            raw_pid = self.path.read_text(encoding="ascii").strip()
        except OSError:
            return False
        if not raw_pid.isdigit():
            return False
        pid = int(raw_pid)
        if pid <= 0 or pid == os.getpid():
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            try:
                self.path.unlink()
                return True
            except OSError:
                return False
        except PermissionError:
            return False
        except OSError:
            return False
        return False

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
    """Perform only local Git mutations bound to one validated task."""

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
            raise GitMutationSafetyStop(
                "Authorized Git mutation requires at least one target"
            )

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
            self._validate_target_files(stage_request.targets)
            self._validate_change_contents(changes)
            if before.head_sha != self._resolve_head_sha():
                raise GitMutationSafetyStop(
                    "Repository HEAD changed during preflight; mutation scope is no longer stable"
                )

            self._run_policy_command(stage_request)
            staged = self.snapshot()
            self._verify_staged_targets(staged, stage_request.targets)
            self._verify_staged_contents(changes, stage_request.targets)

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
            [self.git_executable, "status", "--porcelain=v1", "-z"]
        )
        self._require_success(status_result, "Git status")

        branch_result = self._run_internal(
            [self.git_executable, "branch", "--show-current"]
        )
        self._require_success(branch_result, "Git active-branch resolution")
        branch = branch_result.stdout.strip()
        if not branch:
            raise GitMutationVerificationError(
                "Git active branch could not be proven"
            )

        records = self._parse_status_records(status_result.stdout)
        staged_paths: list[str] = []
        worktree_paths: list[str] = []
        status_lines: list[str] = []
        for index_code, worktree_code, paths in records:
            if index_code not in " MADRCU?!" or worktree_code not in " MADC?U!":
                raise GitMutationVerificationError(
                    f"Unsupported Git status code: {index_code!r}{worktree_code!r}"
                )
            if index_code != " ":
                staged_paths.extend(paths)
            if worktree_code != " ":
                worktree_paths.extend(paths)
            display_paths = " -> ".join(paths) if len(paths) > 1 else paths[0]
            status_lines.append(f"{index_code}{worktree_code} {display_paths}")

        return GitRepositorySnapshot(
            branch=branch,
            status_lines=tuple(status_lines),
            staged_paths=tuple(sorted(set(staged_paths))),
            worktree_paths=tuple(sorted(set(worktree_paths))),
            head_sha=self._resolve_head_sha(),
        )

    @classmethod
    def _parse_status_records(
        cls,
        status_output: str,
    ) -> list[tuple[str, str, tuple[str, ...]]]:
        records: list[tuple[str, str, tuple[str, ...]]] = []
        payload = status_output.encode("utf-8", errors="surrogatepass")
        raw_records = payload.split(b"\0")
        index = 0

        while index < len(raw_records) - 1:
            raw = raw_records[index]
            index += 1
            if not raw:
                continue
            if len(raw) < 3 or raw[2:3] != b" ":
                raise GitMutationVerificationError(
                    "Unparseable NUL-separated Git status record"
                )
            try:
                header = raw[:2].decode("ascii")
                path = raw[3:].decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise GitMutationVerificationError(
                    "Git status contained a non-UTF-8 pathname"
                ) from exc

            index_code, worktree_code = header
            paths = [path]
            if index_code in {"R", "C"} or worktree_code in {"R", "C"}:
                if index >= len(raw_records) - 1:
                    raise GitMutationVerificationError(
                        "Rename/copy status record is missing its source pathname"
                    )
                try:
                    source = raw_records[index].decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise GitMutationVerificationError(
                        "Git rename/copy source pathname is not valid UTF-8"
                    ) from exc
                index += 1
                paths.append(source)

            normalized = tuple(
                cls._normalize_status_path(value)
                for value in paths
            )
            if any(not value for value in normalized):
                raise GitMutationVerificationError(
                    "Git status contained an empty pathname"
                )
            records.append((index_code, worktree_code, normalized))

        return records

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
            raise GitMutationSafetyStop(
                "Working-tree state cannot be proven task-scoped"
            )

    def _validate_target_files(self, targets: Sequence[str]) -> None:
        for target in targets:
            candidate = (self.workspace_root / target).resolve(strict=False)
            try:
                candidate.relative_to(self.workspace_root)
            except ValueError as exc:
                raise GitMutationSafetyStop(
                    f"Git mutation target escapes active workspace: {target!r}"
                ) from exc
            relative = candidate.relative_to(self.workspace_root)
            current = self.workspace_root
            for part in relative.parts:
                current = current / part
                if current.is_symlink():
                    raise GitMutationSafetyStop(
                        f"Git mutation target contains a symlink/junction: {target!r}"
                    )
            if not candidate.exists():
                raise GitMutationSafetyStop(
                    f"Git mutation target does not exist: {target!r}"
                )
            if not candidate.is_file():
                raise GitMutationSafetyStop(
                    f"Git mutation target is not a regular file: {target!r}"
                )

    def _validate_change_contents(self, changes: Sequence[FileChange]) -> None:
        for change in changes:
            if not isinstance(change, FileChange):
                raise GitMutationSafetyStop(
                    "Git mutation content validation requires FileChange records"
                )
            target = self.policy_path(change.path)
            try:
                current = target.read_text(encoding="utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise GitMutationSafetyStop(
                    f"Git mutation target is not valid UTF-8 text: {change.path!r}"
                ) from exc
            if current != change.new_text:
                raise GitMutationSafetyStop(
                    f"Validated mutation content no longer matches target: {change.path!r}"
                )

    def _verify_staged_contents(
        self,
        changes: Sequence[FileChange],
        targets: Sequence[str],
    ) -> None:
        format_result = self._run_internal(
            [self.git_executable, "rev-parse", "--show-object-format"]
        )
        self._require_success(format_result, "Git object-format resolution")
        object_format = format_result.stdout.strip().lower()
        if object_format not in {"sha1", "sha256"}:
            raise GitMutationVerificationError(
                "Unsupported Git object format; staged-content verification cannot be proven"
            )

        expected_by_path = {
            self._normalize_status_path(change.path): change.new_text
            for change in changes
        }
        for target in targets:
            if target not in expected_by_path:
                raise GitMutationVerificationError(
                    f"Validated content missing for staged target: {target!r}"
                )
            content = expected_by_path[target].encode("utf-8")
            header = f"blob {len(content)}\0".encode("ascii")
            digest = hashlib.sha1 if object_format == "sha1" else hashlib.sha256
            expected_oid = digest(header + content).hexdigest()
            result = self._run_internal(
                [self.git_executable, "ls-files", "--stage", "--", target]
            )
            self._require_success(result, "Git staged-index inspection")
            entries = [line for line in result.stdout.splitlines() if line.strip()]
            if len(entries) != 1:
                raise GitMutationVerificationError(
                    f"Staged index evidence is ambiguous for target: {target!r}"
                )
            fields = entries[0].split()
            if len(fields) < 3 or fields[1] != expected_oid:
                actual = fields[1] if len(fields) > 1 else ""
                raise GitMutationVerificationError(
                    f"Staged content differs from validated FileChange.new_text for {target!r}: expected={expected_oid!r} actual={actual!r}"
                )

    def policy_path(self, target: str) -> Path:
        candidate = (self.workspace_root / target).resolve(strict=False)
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError as exc:
            raise GitMutationSafetyStop(
                f"Git mutation target escapes active workspace: {target!r}"
            ) from exc
        return candidate

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
        if len(sha) not in {40, 64} or any(
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
        if not before.head_sha or after.head_sha == before.head_sha:
            raise GitMutationVerificationError(
                "Post-commit HEAD did not advance from the pre-mutation repository state"
            )
        if after.head_sha != commit_sha:
            raise GitMutationVerificationError(
                "Resolved HEAD does not match the post-commit repository snapshot"
            )

        show = self._run_internal(
            [self.git_executable, "show", "--format=", "--name-only", "-z", commit_sha]
        )
        self._require_success(show, "Git commit inspection")
        try:
            verify_exact_target_set(show.stdout, targets)
        except GitCommitEvidenceError as exc:
            raise GitMutationVerificationError(str(exc)) from exc

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
        return value.replace("\\", "/")

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
