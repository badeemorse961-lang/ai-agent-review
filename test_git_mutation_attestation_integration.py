from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from execution_gate import FileChange
from git_mutation_attestation import attestation_from_dict, verify_attestation_binding
from git_mutation_executor import GitMutationExecutor, GitMutationResult
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


def authorized_evidence(target: str, task_id: str, worker_id: str) -> ValidationVerdict:
    return ValidationVerdict(
        task_id=task_id,
        worker_id=worker_id,
        passed=True,
        reasons=(),
        evidence={"passed": True, "changed_targets": [target], "validated": True},
    )


def _executor(workspace: Path) -> GitMutationExecutor:
    git_executable = Path(shutil.which("git") or "git").resolve()
    sandbox = ProcessSandbox(
        WorkspaceResourcePolicy(workspace, allowed_tool_paths=[git_executable]),
        timeout_seconds=5,
    )
    return GitMutationExecutor(workspace, process_sandbox=sandbox)


def test_successful_transaction_result_contains_bound_attestation(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    run_git(workspace, "init")
    run_git(workspace, "config", "user.name", "Agent Test")
    run_git(workspace, "config", "user.email", "agent-test@example.invalid")
    path = workspace / "calculator.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")
    run_git(workspace, "add", "--", "calculator.py")
    run_git(workspace, "commit", "-m", "baseline")

    change = FileChange("calculator.py", "VALUE = 1\n", "VALUE = 2\n")
    path.write_text(change.new_text, encoding="utf-8")
    task_id = "task-attested"
    worker_id = "worker-attested"

    result = _executor(workspace).execute(
        verdict=authorized_evidence("calculator.py", task_id, worker_id),
        checkpoint={"isolated": True, "transaction_id": task_id},
        changes=[change],
        commit_message="agent: attested transaction",
    )

    assert isinstance(result, GitMutationResult)
    assert result.attestation is not None
    attestation = result.attestation
    assert attestation.task_id == task_id
    assert attestation.worker_id == worker_id
    assert attestation.workspace == str(workspace.resolve())
    assert attestation.targets == ("calculator.py",)
    assert attestation.commit_sha == result.commit_sha
    assert len(attestation.staged_evidence_sha256) == 64
    assert len(attestation.commit_evidence_sha256) == 64
    verify_attestation_binding(
        attestation,
        task_id=task_id,
        worker_id=worker_id,
        workspace=workspace,
        targets=("calculator.py",),
        commit_sha=result.commit_sha or "",
    )

    persisted = json.loads(
        (workspace / ".agent_runtime" / "git_mutation_state.json").read_text(
            encoding="utf-8"
        )
    )
    restored = attestation_from_dict(persisted["attestation"])
    assert restored == attestation
    assert persisted["commit_sha"] == result.commit_sha
    assert persisted["attestation"]["commit_sha"] == result.commit_sha


def test_attestation_digest_is_stable_across_result_serialization(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    run_git(workspace, "init")
    run_git(workspace, "config", "user.name", "Agent Test")
    run_git(workspace, "config", "user.email", "agent-test@example.invalid")
    path = workspace / "calculator.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")
    run_git(workspace, "add", "--", "calculator.py")
    run_git(workspace, "commit", "-m", "baseline")
    change = FileChange("calculator.py", "VALUE = 1\n", "VALUE = 4\n")
    path.write_text(change.new_text, encoding="utf-8")

    result = _executor(workspace).execute(
        verdict=authorized_evidence("calculator.py", "task-serialization", "worker-serialization"),
        checkpoint={"isolated": True, "transaction_id": "task-serialization"},
        changes=[change],
        commit_message="agent: serialization evidence",
    )

    payload = result.to_dict()
    restored = attestation_from_dict(payload["attestation"])
    assert restored == result.attestation


def test_attestation_binding_rejects_commit_identity_drift(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    run_git(workspace, "init")
    run_git(workspace, "config", "user.name", "Agent Test")
    run_git(workspace, "config", "user.email", "agent-test@example.invalid")
    path = workspace / "calculator.py"
    path.write_text("VALUE = 1\n", encoding="utf-8")
    run_git(workspace, "add", "--", "calculator.py")
    run_git(workspace, "commit", "-m", "baseline")
    change = FileChange("calculator.py", "VALUE = 1\n", "VALUE = 5\n")
    path.write_text(change.new_text, encoding="utf-8")

    result = _executor(workspace).execute(
        verdict=authorized_evidence("calculator.py", "task-drift", "worker-drift"),
        checkpoint={"isolated": True, "transaction_id": "task-drift"},
        changes=[change],
        commit_message="agent: drift evidence",
    )

    assert result.attestation is not None
    import pytest

    with pytest.raises(Exception, match="not bound"):
        verify_attestation_binding(
            result.attestation,
            task_id="task-drift",
            worker_id="worker-drift",
            workspace=workspace,
            targets=("calculator.py",),
            commit_sha="a" * len(result.commit_sha or ""),
        )
