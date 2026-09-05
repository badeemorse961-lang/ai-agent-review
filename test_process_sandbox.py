from __future__ import annotations

import sys
from pathlib import Path

import pytest

from process_sandbox import ProcessSandbox, ProcessSandboxSafetyStop
from sandbox_policy import WorkspaceResourcePolicy


def make_sandbox(tmp_path: Path) -> ProcessSandbox:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = Path(sys.executable).resolve()
    policy = WorkspaceResourcePolicy(workspace, allowed_tool_paths=[executable])
    return ProcessSandbox(policy, timeout_seconds=2, max_output_chars=256)


def test_runs_explicit_tool_without_shell(tmp_path: Path) -> None:
    sandbox = make_sandbox(tmp_path)
    result = sandbox.run([str(Path(sys.executable).resolve()), "-c", "print('x')"])
    assert result.returncode == 0
    assert result.stdout.strip() == "x"
    assert result.isolated_process_group is True


def test_inline_launcher_is_rejected_by_sandbox(tmp_path: Path) -> None:
    sandbox = make_sandbox(tmp_path)
    with pytest.raises(ProcessSandboxSafetyStop):
        sandbox.run([str(Path(sys.executable).resolve()), "-m", "pytest"])


def test_unapproved_tool_is_rejected(tmp_path: Path) -> None:
    sandbox = make_sandbox(tmp_path)
    with pytest.raises(ProcessSandboxSafetyStop):
        sandbox.run([str(tmp_path / "not-approved.exe")])


def test_environment_is_secret_minimized(tmp_path: Path) -> None:
    sandbox = make_sandbox(tmp_path)
    result = sandbox.run(
        [str(Path(sys.executable).resolve()), "-c", "import os; print(os.getenv('API_KEY')); print(os.getenv('AGENT_TEST'))"],
        env={"AGENT_TEST": "ok"},
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["None", "ok"]


def test_external_access_must_be_declared(tmp_path: Path) -> None:
    sandbox = make_sandbox(tmp_path)
    with pytest.raises(ProcessSandboxSafetyStop):
        sandbox.run(
            [str(Path(sys.executable).resolve()), "-c", "print('x')"],
            external_reads=[tmp_path / "unmanaged" / "data.txt"],
        )


def test_strict_os_mode_fails_closed_until_native_backend_exists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = WorkspaceResourcePolicy(workspace, allowed_tool_paths=[Path(sys.executable).resolve()])
    with pytest.raises(ProcessSandboxSafetyStop):
        ProcessSandbox(policy, containment_mode="strict_os_required")
