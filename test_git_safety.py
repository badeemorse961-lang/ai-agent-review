from __future__ import annotations

from pathlib import Path

import pytest

from git_safety import GitSafetyPolicy
from process_sandbox import ProcessSandboxSafetyStop


@pytest.fixture()
def git_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    return workspace


def test_read_only_git_status_is_allowed(git_workspace: Path) -> None:
    policy = GitSafetyPolicy()

    assert policy.validate(
        ["git", "status", "--short", "--branch"],
        workspace_root=git_workspace,
    ) == ("git", "status", "--short", "--branch")


def test_read_only_git_queries_are_allowlisted(git_workspace: Path) -> None:
    policy = GitSafetyPolicy()

    for command in (
        ["git", "diff", "--stat", "worker_execution.py"],
        ["git", "log", "--oneline", "--decorate"],
        ["git", "show"],
        ["git", "branch", "--show-current"],
        ["git", "rev-parse", "--show-toplevel"],
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        assert policy.validate(command, workspace_root=git_workspace) == tuple(command)


def test_mutating_git_subcommands_are_rejected(git_workspace: Path) -> None:
    policy = GitSafetyPolicy()
    commands = (
        ["git", "add", "worker_execution.py"],
        ["git", "commit", "-m", "change"],
        ["git", "push"],
        ["git", "pull"],
        ["git", "fetch"],
        ["git", "reset", "--hard"],
        ["git", "clean", "-fd"],
        ["git", "checkout", "main"],
        ["git", "switch", "main"],
        ["git", "restore", "worker_execution.py"],
        ["git", "merge", "topic"],
        ["git", "rebase", "main"],
        ["git", "stash"],
        ["git", "config", "user.name", "agent"],
    )

    for command in commands:
        with pytest.raises(ProcessSandboxSafetyStop):
            policy.validate(command, workspace_root=git_workspace)


def test_git_repository_scope_overrides_are_rejected(git_workspace: Path) -> None:
    policy = GitSafetyPolicy()

    for command in (
        ["git", "--git-dir", str(git_workspace / ".git"), "status"],
        ["git", "--work-tree", str(git_workspace), "status"],
        ["git", "-C", str(git_workspace), "status"],
        ["git", "-c", "core.pager=cat", "status"],
    ):
        with pytest.raises(ProcessSandboxSafetyStop):
            policy.validate(command, workspace_root=git_workspace)


def test_git_path_arguments_must_be_workspace_relative(git_workspace: Path) -> None:
    policy = GitSafetyPolicy()
    outside = git_workspace.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ProcessSandboxSafetyStop):
        policy.validate(
            ["git", "diff", "--", str(outside)],
            workspace_root=git_workspace,
        )


def test_non_git_executable_is_rejected(git_workspace: Path) -> None:
    with pytest.raises(ProcessSandboxSafetyStop):
        GitSafetyPolicy().validate(
            ["python", "worker.py"],
            workspace_root=git_workspace,
        )


def test_non_repository_workspace_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "not-a-repo"
    workspace.mkdir()

    with pytest.raises(ProcessSandboxSafetyStop):
        GitSafetyPolicy().validate(
            ["git", "status"],
            workspace_root=workspace,
        )
