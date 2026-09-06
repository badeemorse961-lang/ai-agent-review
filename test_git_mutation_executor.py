from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from execution_authorization import ExecutionAuthorizationSafetyStop
from execution_gate import FileChange
from git_mutation_executor import (
    GitMutationExecutor,
    GitMutationExecutorError,
    GitMutationVerificationError,
    GitRepositorySnapshot,
    _WorkspaceMutationLock,
)
from git_mutation_policy import GitMutationSafetyStop
from independent_validation import ValidationVerdict
from process_sandbox import ProcessSandbox, ProcessResult
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


def authorized_evidence(
    target: str,
    *,
    task_id: str = "task-1",
    worker_id: str = "worker-1",
) -> ValidationVerdict:
    return ValidationVerdict(
        task_id=task_id,
        worker_id=worker_id,
        passed=True,
        reasons=(),
        evidence={"changed_targets": [target], "validated": True},
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


def change_for(workspace: Path, *, new_value: str = "VALUE = 2\n") -> FileChange:
    current = (workspace / "calculator.py").read_text(encoding="utf-8")
    return FileChange(
        path="calculator.py",
        old_text=current,
        new_text=new_value,
    )


def execute_authorized(
    executor: GitMutationExecutor,
    change: FileChange,
    *,
    task_id: str = "task-1",
    worker_id: str = "worker-1",
    commit_message: str = "agent: update calculator value",
):
    return executor.execute(
        verdict=authorized_evidence(
            change.path,
            task_id=task_id,
            worker_id=worker_id,
        ),
        checkpoint={"isolated": True, "transaction_id": task_id},
        changes=[change],
        commit_message=commit_message,
    )


def test_control_plane_stages_and_commits_exact_authorized_targets(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    change = change_for(workspace)
    (workspace / "calculator.py").write_text(change.new_text, encoding="utf-8")

    result = execute_authorized(executor, change)

    assert result.committed is True
    assert result.verified is True
    assert result.commit_sha
    assert result.targets == ("calculator.py",)
    assert result.before.staged_paths == ()
    assert result.after.staged_paths == ()
    assert result.after.worktree_paths == ()

    audit = json.loads(
        (workspace / ".agent_runtime" / "git_mutation_state.json").read_text(
            encoding="utf-8"
        )
    )
    assert audit["task_id"] == "task-1"
    assert audit["targets"] == ["calculator.py"]
    assert "agent: update calculator value" not in json.dumps(audit)

    shown = run_git(
        workspace,
        "show",
        "--format=%s",
        "--name-only",
        result.commit_sha,
    ).stdout.splitlines()
    assert shown[0] == "agent: update calculator value"
    assert "calculator.py" in shown


def test_mutation_requires_passed_independent_validation(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    change = change_for(workspace)
    (workspace / "calculator.py").write_text(change.new_text, encoding="utf-8")

    verdict = ValidationVerdict(
        task_id="task-1",
        worker_id="worker-1",
        passed=False,
        reasons=("validator failed",),
        evidence={"changed_targets": [change.path]},
    )
    with pytest.raises(ExecutionAuthorizationSafetyStop):
        executor.execute(
            verdict=verdict,
            checkpoint={"isolated": True},
            changes=[change],
            commit_message="agent: blocked",
        )

    assert " M calculator.py" in run_git(
        workspace,
        "status",
        "--porcelain=v1",
    ).stdout


def test_mutation_requires_isolated_checkpoint(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    change = change_for(workspace)
    (workspace / "calculator.py").write_text(change.new_text, encoding="utf-8")

    with pytest.raises(ExecutionAuthorizationSafetyStop):
        executor.execute(
            verdict=authorized_evidence("calculator.py"),
            checkpoint={"isolated": False},
            changes=[change],
            commit_message="agent: blocked",
        )

    assert (workspace / "calculator.py").read_text(encoding="utf-8") == change.new_text


def test_missing_or_non_file_targets_are_rejected(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    missing = FileChange(path="missing.py", old_text="old\n", new_text="new\n")
    with pytest.raises(GitMutationSafetyStop):
        executor.execute(
            verdict=authorized_evidence("missing.py"),
            checkpoint={"isolated": True},
            changes=[missing],
            commit_message="agent: missing target",
        )

    directory = FileChange(path="nested", old_text="old\n", new_text="new\n")
    (workspace / "nested").mkdir()
    with pytest.raises(GitMutationSafetyStop):
        executor.execute(
            verdict=authorized_evidence("nested"),
            checkpoint={"isolated": True},
            changes=[directory],
            commit_message="agent: directory target",
        )


def test_symlink_target_is_rejected(repo: tuple[Path, GitMutationExecutor]) -> None:
    workspace, executor = repo
    outside = workspace.parent / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    link = workspace / "linked.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable on this host")

    change = FileChange(path="linked.txt", old_text="outside\n", new_text="changed\n")
    with pytest.raises(GitMutationSafetyStop):
        executor.execute(
            verdict=authorized_evidence("linked.txt"),
            checkpoint={"isolated": True},
            changes=[change],
            commit_message="agent: symlink target",
        )


def test_preflight_rejects_unrelated_worktree_changes(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    change = change_for(workspace)
    (workspace / "calculator.py").write_text(change.new_text, encoding="utf-8")
    (workspace / "README.md").write_text("unrelated\n", encoding="utf-8")

    with pytest.raises(GitMutationSafetyStop):
        execute_authorized(executor, change)

    status = run_git(workspace, "status", "--porcelain=v1").stdout
    assert "calculator.py" in status
    assert "README.md" in status


def test_preflight_rejects_existing_staged_changes(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    change = change_for(workspace)
    (workspace / "calculator.py").write_text(change.new_text, encoding="utf-8")
    run_git(workspace, "add", "--", "calculator.py")

    with pytest.raises(GitMutationSafetyStop):
        execute_authorized(
            executor,
            FileChange(
                path="README.md",
                old_text="baseline\n",
                new_text="changed\n",
            ),
        )


def test_target_escape_is_rejected_before_git_invocation(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    _, executor = repo
    change = FileChange(
        path="../outside.py",
        old_text="old\n",
        new_text="new\n",
    )

    with pytest.raises((GitMutationSafetyStop, ExecutionAuthorizationSafetyStop)):
        executor.execute(
            verdict=authorized_evidence(
                "../outside.py",
                task_id="task-4",
                worker_id="worker-4",
            ),
            checkpoint={"isolated": True},
            changes=[change],
            commit_message="agent: blocked",
        )


def test_commit_failure_preserves_staged_evidence(
    repo: tuple[Path, GitMutationExecutor],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, executor = repo
    change = change_for(workspace, new_value="VALUE = 4\n")
    (workspace / "calculator.py").write_text(change.new_text, encoding="utf-8")

    original = executor._run_policy_command

    def fail_commit(request):
        if request.operation == "commit":
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
        execute_authorized(
            executor,
            change,
            commit_message="agent: hook failure evidence",
        )

    assert run_git(
        workspace,
        "diff",
        "--cached",
        "--name-only",
    ).stdout.strip() == "calculator.py"


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


def test_snapshot_parses_branch_and_scoped_status(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    (workspace / "calculator.py").write_text("VALUE = 9\n", encoding="utf-8")
    snapshot = executor.snapshot()
    assert snapshot.branch in {"main", "master"}
    assert snapshot.staged_paths == ()
    assert snapshot.worktree_paths == ("calculator.py",)


def test_verification_failure_is_fail_closed(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    _, executor = repo
    fake_before = GitRepositorySnapshot("main", (), (), ())
    fake_after = GitRepositorySnapshot("main", (), (), ("unexpected.py",))
    with pytest.raises(GitMutationVerificationError):
        executor._verify_post_commit(
            fake_after,
            "0123456789abcdef",
            ("calculator.py",),
            fake_before,
        )


def test_workspace_mutation_lock_is_exclusive(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, _ = repo
    first = _WorkspaceMutationLock(workspace)
    second = _WorkspaceMutationLock(workspace)
    with first:
        with pytest.raises(GitMutationSafetyStop):
            with second:
                pass
    assert not first.path.exists()
