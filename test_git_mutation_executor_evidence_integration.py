from __future__ import annotations

import hashlib
from pathlib import Path
from collections.abc import Sequence

import pytest

from execution_gate import FileChange
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


def _result(stdout: str) -> ProcessResult:
    return ProcessResult(
        returncode=0,
        stdout=stdout,
        stderr="",
        timed_out=False,
        truncated=False,
        isolated_process_group=True,
        containment_mode="workspace_guarded",
    )


def _snapshot(head: str = "2" * 40) -> GitRepositorySnapshot:
    return GitRepositorySnapshot(
        branch="main",
        status_lines=(),
        staged_paths=("calculator.py",),
        worktree_paths=(),
        head_sha=head,
    )


def test_staged_content_verification_uses_one_nul_delimited_index_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = _executor_without_runtime()
    content = "VALUE = 2\n"
    digest = hashlib.sha1
    object_id = digest(f"blob {len(content.encode('utf-8'))}\0".encode("ascii") + content.encode("utf-8")).hexdigest()
    calls: list[tuple[str, ...]] = []

    def fake_run_internal(command: Sequence[str]) -> ProcessResult:
        calls.append(tuple(command))
        if tuple(command[1:]) == ("rev-parse", "--show-object-format"):
            return _result("sha1\n")
        if tuple(command[1:]) == ("ls-files", "--stage", "-z", "--", "calculator.py"):
            return _result(f"100644 {object_id} 0\tcalculator.py\0")
        raise AssertionError(f"unexpected command: {command!r}")

    monkeypatch.setattr(executor, "_run_internal", fake_run_internal)
    executor._verify_staged_contents(
        [FileChange("calculator.py", "VALUE = 1\n", content)],
        ("calculator.py",),
    )

    assert calls == [
        ("git", "rev-parse", "--show-object-format"),
        ("git", "ls-files", "--stage", "-z", "--", "calculator.py"),
    ]


def test_staged_content_verification_rejects_line_oriented_index_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = _executor_without_runtime()
    content = "VALUE = 2\n"
    object_id = hashlib.sha1(
        f"blob {len(content.encode('utf-8'))}\0".encode("ascii") + content.encode("utf-8")
    ).hexdigest()

    def fake_run_internal(command: Sequence[str]) -> ProcessResult:
        if tuple(command[1:]) == ("rev-parse", "--show-object-format"):
            return _result("sha1\n")
        return _result(f"100644 {object_id} 0\tcalculator.py\n")

    monkeypatch.setattr(executor, "_run_internal", fake_run_internal)
    with pytest.raises(GitMutationVerificationError, match="not NUL-delimited"):
        executor._verify_staged_contents(
            [FileChange("calculator.py", "VALUE = 1\n", content)],
            ("calculator.py",),
        )


def test_post_commit_and_staged_evidence_share_exact_target_contract() -> None:
    executor = _executor_without_runtime()
    after = _snapshot()
    before = GitRepositorySnapshot("main", (), (), (), "1" * 40)
    assert after.staged_paths == ("calculator.py",)
    assert before.head_sha != after.head_sha
