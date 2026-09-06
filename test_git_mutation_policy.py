from __future__ import annotations

from pathlib import Path

import pytest

from git_mutation_policy import (
    GitMutationPolicy,
    GitMutationSafetyStop,
)


@pytest.fixture()
def git_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    return workspace


def test_stage_request_is_exactly_target_scoped(git_workspace: Path) -> None:
    policy = GitMutationPolicy()
    request = policy.validate_request(
        task_id="task-1",
        worker_id="worker-1",
        operation="stage",
        targets=["calculator.py", "tests/test_calculator.py"],
        workspace_root=git_workspace,
    )

    assert request.targets == ("calculator.py", "tests/test_calculator.py")
    assert policy.command(request) == (
        "git",
        "add",
        "--",
        "calculator.py",
        "tests/test_calculator.py",
    )


def test_commit_request_requires_bounded_single_line_message(git_workspace: Path) -> None:
    policy = GitMutationPolicy()
    request = policy.validate_request(
        task_id="task-1",
        worker_id="worker-1",
        operation="commit",
        targets=["calculator.py"],
        commit_message="agent: verified calculator fix",
        workspace_root=git_workspace,
    )

    assert policy.command(request) == (
        "git",
        "commit",
        "-m",
        "agent: verified calculator fix",
    )

    with pytest.raises(GitMutationSafetyStop):
        policy.validate_request(
            task_id="task-1",
            worker_id="worker-1",
            operation="commit",
            targets=["calculator.py"],
            commit_message="line one\nline two",
            workspace_root=git_workspace,
        )


def test_absolute_and_traversal_targets_are_rejected(git_workspace: Path) -> None:
    policy = GitMutationPolicy()

    for target in (str(git_workspace / "file.py"), "../file.py", "./file.py"):
        with pytest.raises(GitMutationSafetyStop):
            policy.validate_request(
                task_id="task-1",
                worker_id="worker-1",
                operation="stage",
                targets=[target],
                workspace_root=git_workspace,
            )


def test_duplicate_targets_and_unsupported_operations_are_rejected(git_workspace: Path) -> None:
    policy = GitMutationPolicy()

    with pytest.raises(GitMutationSafetyStop):
        policy.validate_request(
            task_id="task-1",
            worker_id="worker-1",
            operation="stage",
            targets=["calculator.py", "calculator.py"],
            workspace_root=git_workspace,
        )

    for operation in ("push", "pull", "fetch", "reset", "clean", "checkout", "merge", "rebase"):
        with pytest.raises(GitMutationSafetyStop):
            policy.validate_request(
                task_id="task-1",
                worker_id="worker-1",
                operation=operation,
                targets=["calculator.py"],
                workspace_root=git_workspace,
            )


def test_command_must_match_request_exactly(git_workspace: Path) -> None:
    policy = GitMutationPolicy()
    request = policy.validate_request(
        task_id="task-1",
        worker_id="worker-1",
        operation="stage",
        targets=["calculator.py"],
        workspace_root=git_workspace,
    )

    assert policy.validate_command(
        ["git", "add", "--", "calculator.py"],
        request=request,
        workspace_root=git_workspace,
    ) == ("git", "add", "--", "calculator.py")

    with pytest.raises(GitMutationSafetyStop):
        policy.validate_command(
            ["git", "add", "--", "other.py"],
            request=request,
            workspace_root=git_workspace,
        )

    with pytest.raises(GitMutationSafetyStop):
        policy.validate_command(
            ["git", "add", "-A"],
            request=request,
            workspace_root=git_workspace,
        )


def test_dangerous_commit_flags_are_rejected(git_workspace: Path) -> None:
    policy = GitMutationPolicy()
    request = policy.validate_request(
        task_id="task-1",
        worker_id="worker-1",
        operation="commit",
        targets=["calculator.py"],
        commit_message="verified change",
        workspace_root=git_workspace,
    )

    for command in (
        ["git", "commit", "--amend", "-m", "verified change"],
        ["git", "commit", "--no-verify", "-m", "verified change"],
        ["git", "commit", "-c", "core.hooksPath=x", "-m", "verified change"],
    ):
        with pytest.raises(GitMutationSafetyStop):
            policy.validate_command(
                command,
                request=request,
                workspace_root=git_workspace,
            )
