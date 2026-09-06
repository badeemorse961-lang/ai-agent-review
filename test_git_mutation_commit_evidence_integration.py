from __future__ import annotations

from pathlib import Path

import pytest

from git_mutation_executor import (
    GitMutationExecutor,
    GitMutationVerificationError,
    GitRepositorySnapshot,
)
from process_sandbox import ProcessResult


def _executor_without_runtime() -> GitMutationExecutor:
    executor = GitMutationExecutor.__new__(GitMutationExecutor)
    executor.git_executable = "git"
    executor.workspace_root = Path(".").resolve()
    return executor


def _snapshot(*, worktree_paths: tuple[str, ...] = ()) -> GitRepositorySnapshot:
    return GitRepositorySnapshot(
        branch="main",
        status_lines=(),
        staged_paths=(),
        worktree_paths=worktree_paths,
        head_sha="1" * 40,
    )


def test_post_commit_verification_uses_nul_delimited_git_show(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = _executor_without_runtime()
    calls: list[tuple[str, ...]] = []

    def fake_run_internal(command: tuple[str, ...]) -> ProcessResult:
        calls.append(command)
        return ProcessResult(
            returncode=0,
            stdout="calculator.py\x00README.md\x00",
            stderr="",
            timed_out=False,
            truncated=False,
            isolated_process_group=True,
            containment_mode="workspace_guarded",
        )

    monkeypatch.setattr(executor, "_run_internal", fake_run_internal)

    before = _snapshot()
    after = _snapshot()
    after = GitRepositorySnapshot(
        branch=after.branch,
        status_lines=after.status_lines,
        staged_paths=after.staged_paths,
        worktree_paths=after.worktree_paths,
        head_sha="2" * 40,
    )

    executor._verify_post_commit(
        after,
        "2" * 40,
        ("calculator.py", "README.md"),
        before,
    )

    assert calls == [("git", "show", "--format=", "--name-only", "-z", "2" * 40)]


def test_post_commit_verification_rejects_line_oriented_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = _executor_without_runtime()

    def fake_run_internal(_: tuple[str, ...]) -> ProcessResult:
        return ProcessResult(
            returncode=0,
            stdout="calculator.py\nREADME.md\n",
            stderr="",
            timed_out=False,
            truncated=False,
            isolated_process_group=True,
            containment_mode="workspace_guarded",
        )

    monkeypatch.setattr(executor, "_run_internal", fake_run_internal)

    with pytest.raises(GitMutationVerificationError, match="not NUL-delimited"):
        executor._verify_post_commit(
            GitRepositorySnapshot("main", (), (), (), "2" * 40),
            "2" * 40,
            ("calculator.py", "README.md"),
            GitRepositorySnapshot("main", (), (), (), "1" * 40),
        )


def test_post_commit_verification_rejects_ambiguous_duplicate_path_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = _executor_without_runtime()

    def fake_run_internal(_: tuple[str, ...]) -> ProcessResult:
        return ProcessResult(
            returncode=0,
            stdout="calculator.py\x00calculator.py\x00",
            stderr="",
            timed_out=False,
            truncated=False,
            isolated_process_group=True,
            containment_mode="workspace_guarded",
        )

    monkeypatch.setattr(executor, "_run_internal", fake_run_internal)

    with pytest.raises(GitMutationVerificationError, match="duplicate records"):
        executor._verify_post_commit(
            GitRepositorySnapshot("main", (), (), (), "2" * 40),
            "2" * 40,
            ("calculator.py", "README.md"),
            GitRepositorySnapshot("main", (), (), (), "1" * 40),
        )


def test_post_commit_verification_rejects_unexpected_exact_target_set(monkeypatch: pytest.MonkeyPatch) -> None:
    executor = _executor_without_runtime()

    def fake_run_internal(_: tuple[str, ...]) -> ProcessResult:
        return ProcessResult(
            returncode=0,
            stdout="calculator.py\x00other.py\x00",
            stderr="",
            timed_out=False,
            truncated=False,
            isolated_process_group=True,
            containment_mode="workspace_guarded",
        )

    monkeypatch.setattr(executor, "_run_internal", fake_run_internal)

    with pytest.raises(GitMutationVerificationError, match="Committed target set mismatch"):
        executor._verify_post_commit(
            GitRepositorySnapshot("main", (), (), (), "2" * 40),
            "2" * 40,
            ("calculator.py", "README.md"),
            GitRepositorySnapshot("main", (), (), (), "1" * 40),
        )
