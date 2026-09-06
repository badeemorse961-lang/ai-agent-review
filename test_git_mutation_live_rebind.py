from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from execution_gate import FileChange
from git_mutation_executor import GitMutationExecutor
from git_mutation_live_rebind import (
    GitMutationLiveRebindError,
    rebind_live_git_mutation_result,
)
from independent_validation import ValidationVerdict
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


def make_executor(workspace: Path) -> GitMutationExecutor:
    git_executable = Path(shutil.which("git") or "git").resolve()
    sandbox = ProcessSandbox(
        WorkspaceResourcePolicy(workspace, allowed_tool_paths=[git_executable]),
        timeout_seconds=5,
    )
    return GitMutationExecutor(workspace, process_sandbox=sandbox)


def make_repo(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    workspace.mkdir(parents=True)
    run_git(workspace, "init")
    run_git(workspace, "switch", "-c", "main")
    run_git(workspace, "config", "user.name", "Agent Test")
    run_git(workspace, "config", "user.email", "agent-test@example.invalid")
    (workspace / ".gitignore").write_text(".agent_runtime/\n", encoding="utf-8")
    (workspace / "calculator.py").write_text("VALUE = 1\n", encoding="utf-8")
    run_git(workspace, "add", "--", ".gitignore", "calculator.py")
    run_git(workspace, "commit", "-m", "baseline")
    return workspace


def execute_attested(workspace: Path):
    path = workspace / "calculator.py"
    change = FileChange("calculator.py", "VALUE = 1\n", "VALUE = 2\n")
    path.write_text(change.new_text, encoding="utf-8")
    task_id = "task-live-rebind"
    worker_id = "worker-live-rebind"
    executor = make_executor(workspace)
    result = executor.execute(
        verdict=ValidationVerdict(
            task_id=task_id,
            worker_id=worker_id,
            passed=True,
            reasons=(),
            evidence={"changed_targets": [change.path], "validated": True},
        ),
        checkpoint={"isolated": True, "transaction_id": task_id},
        changes=[change],
        commit_message="agent: live rebind",
    )
    return executor, result


def test_live_rebind_accepts_unchanged_verified_transaction(tmp_path: Path) -> None:
    workspace = make_repo(tmp_path)
    executor, result = execute_attested(workspace)

    evidence = rebind_live_git_mutation_result(
        result,
        workspace_root=workspace,
        process_sandbox=executor.process_sandbox,
    )

    assert evidence.task_id == result.task_id
    assert evidence.worker_id == result.worker_id
    assert evidence.workspace == str(workspace.resolve())
    assert evidence.branch == result.after.branch
    assert evidence.head_sha == result.commit_sha
    assert evidence.targets == result.targets
    assert result.attestation is not None
    assert evidence.commit_evidence_sha256 == result.attestation.commit_evidence_sha256


def test_live_rebind_rejects_worktree_drift(tmp_path: Path) -> None:
    workspace = make_repo(tmp_path)
    executor, result = execute_attested(workspace)
    (workspace / "calculator.py").write_text("VALUE = attacker\n", encoding="utf-8")

    with pytest.raises(GitMutationLiveRebindError, match="not clean"):
        rebind_live_git_mutation_result(
            result,
            workspace_root=workspace,
            process_sandbox=executor.process_sandbox,
        )


def test_live_rebind_rejects_branch_drift(tmp_path: Path) -> None:
    workspace = make_repo(tmp_path)
    executor, result = execute_attested(workspace)
    run_git(workspace, "switch", "-c", "other-branch")

    with pytest.raises(GitMutationLiveRebindError, match="branch drifted"):
        rebind_live_git_mutation_result(
            result,
            workspace_root=workspace,
            process_sandbox=executor.process_sandbox,
        )


def test_live_rebind_rejects_head_drift(tmp_path: Path) -> None:
    workspace = make_repo(tmp_path)
    executor, result = execute_attested(workspace)
    run_git(workspace, "commit", "--allow-empty", "-m", "unrelated live drift")

    with pytest.raises(GitMutationLiveRebindError, match="HEAD"):
        rebind_live_git_mutation_result(
            result,
            workspace_root=workspace,
            process_sandbox=executor.process_sandbox,
        )


def test_live_rebind_rejects_attested_digest_drift(tmp_path: Path) -> None:
    workspace = make_repo(tmp_path)
    executor, result = execute_attested(workspace)
    assert result.attestation is not None
    altered = replace(
        result,
        attestation=replace(result.attestation, commit_evidence_sha256="f" * 64),
    )

    with pytest.raises(GitMutationLiveRebindError, match="digest"):
        rebind_live_git_mutation_result(
            altered,
            workspace_root=workspace,
            process_sandbox=executor.process_sandbox,
        )


def test_live_rebind_rejects_wrong_process_sandbox_workspace(tmp_path: Path) -> None:
    workspace = make_repo(tmp_path)
    executor, result = execute_attested(workspace)
    other = make_repo(tmp_path / "other")
    other_executor = make_executor(other)

    with pytest.raises(GitMutationLiveRebindError, match="process sandbox"):
        rebind_live_git_mutation_result(
            result,
            workspace_root=workspace,
            process_sandbox=other_executor.process_sandbox,
        )
