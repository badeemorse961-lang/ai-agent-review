from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from git_mutation_executor import (
    GitMutationExecutor,
    GitMutationExecutorError,
)
from git_mutation_policy import GitMutationSafetyStop
from process_sandbox import ProcessSandbox
from sandbox_policy import WorkspaceResourcePolicy


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shutil.which("git") or "git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
        shell=False,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> tuple[Path, GitMutationExecutor]:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    run_git(workspace, "init")
    run_git(workspace, "config", "user.name", "Agent Test")
    run_git(workspace, "config", "user.email", "agent-test@example.invalid")
    (workspace / "calculator.py").write_text("VALUE = 1\n", encoding="utf-8")
    (workspace / "README.md").write_text("baseline\n", encoding="utf-8")
    run_git(workspace, "add", "--", "calculator.py", "README.md")
    run_git(workspace, "commit", "-m", "baseline")

    git_executable = Path(shutil.which("git") or "git").resolve()
    sandbox = ProcessSandbox(
        WorkspaceResourcePolicy(
            workspace,
            allowed_tool_paths=[git_executable],
        ),
        timeout_seconds=5,
    )
    return workspace, GitMutationExecutor(workspace, process_sandbox=sandbox)


def test_control_plane_stages_and_commits_exact_targets(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    (workspace / "calculator.py").write_text("VALUE = 2\n", encoding="utf-8")

    result = executor.execute(
        task_id="task-1",
        worker_id="worker-1",
        targets=["calculator.py"],
        commit_message="agent: update calculator value",
    )

    assert result.committed is True
    assert result.verified is True
    assert result.commit_sha
    assert result.targets == ("calculator.py",)
    assert result.before.staged_paths == ()
    assert result.after.staged_paths == ()
    assert result.after.worktree_paths == ()
    assert (workspace / ".agent_runtime" / "git_mutation_state.json").exists()

    shown = run_git(
        workspace,
        "show",
        "--format=%s",
        "--name-only",
        result.commit_sha,
    ).stdout.splitlines()
    assert shown[0] == "agent: update calculator value"
    assert shown[2:] == ["calculator.py"]


def test_preflight_rejects_unrelated_worktree_changes(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    (workspace / "calculator.py").write_text("VALUE = 2\n", encoding="utf-8")
    (workspace / "README.md").write_text("unrelated\n", encoding="utf-8")

    with pytest.raises(GitMutationSafetyStop):
        executor.execute(
            task_id="task-2",
            worker_id="worker-2",
            targets=["calculator.py"],
            commit_message="agent: scoped change",
        )

    status = run_git(workspace, "status", "--porcelain=v1").stdout
    assert "calculator.py" in status
    assert "README.md" in status


def test_preflight_rejects_existing_staged_changes(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    (workspace / "calculator.py").write_text("VALUE = 2\n", encoding="utf-8")
    run_git(workspace, "add", "--", "calculator.py")

    with pytest.raises(GitMutationSafetyStop):
        executor.execute(
            task_id="task-3",
            worker_id="worker-3",
            targets=["README.md"],
            commit_message="agent: must not absorb foreign staged work",
        )


def test_target_escape_is_rejected_before_git_invocation(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    _, executor = repo

    with pytest.raises(GitMutationSafetyStop):
        executor.execute(
            task_id="task-4",
            worker_id="worker-4",
            targets=["../outside.py"],
            commit_message="agent: blocked",
        )


def test_commit_failure_does_not_auto_cleanup_staged_evidence(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    (workspace / "calculator.py").write_text("VALUE = 3\n", encoding="utf-8")
    bad_message = ""  # rejected before mutation

    with pytest.raises(GitMutationSafetyStop):
        executor.execute(
            task_id="task-5",
            worker_id="worker-5",
            targets=["calculator.py"],
            commit_message=bad_message,
        )

    assert run_git(workspace, "diff", "--cached", "--name-only").stdout == ""


def test_executor_requires_allowlisted_git_tool(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    other = Path(shutil.which("python") or "python").resolve()
    sandbox = ProcessSandbox(
        WorkspaceResourcePolicy(workspace, allowed_tool_paths=[other]),
        timeout_seconds=5,
    )

    with pytest.raises(GitMutationSafetyStop):
        GitMutationExecutor(workspace, process_sandbox=sandbox)


def test_commit_command_failure_preserves_staged_state(repo: tuple[Path, GitMutationExecutor], monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, executor = repo
    (workspace / "calculator.py").write_text("VALUE = 4\n", encoding="utf-8")

    original = executor._run_policy_command

    def fail_commit(request):
        if request.operation == "commit":
            from process_sandbox import ProcessResult

            return ProcessResult(
                returncode=1,
                stdout="",
                stderr="hook failure",
                timed_out=False,
                truncated=False,
                isolated_process_group=True,
                containment_mode="workspace_guarded",
            )
        return original(request)

    monkeypatch.setattr(executor, "_run_policy_command", fail_commit)

    with pytest.raises(GitMutationExecutorError):
        executor.execute(
            task_id="task-6",
            worker_id="worker-6",
            targets=["calculator.py"],
            commit_message="agent: hook failure evidence",
        )

    assert run_git(workspace, "diff", "--cached", "--name-only").stdout.strip() == "calculator.py"
