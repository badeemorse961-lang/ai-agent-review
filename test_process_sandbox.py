from __future__ import annotations

import sys
from pathlib import Path

import pytest

from process_sandbox import ProcessSandbox, ProcessSandboxSafetyStop
from sandbox_policy import WorkspaceResourcePolicy


def make_sandbox(tmp_path: Path, *, timeout: float = 2) -> ProcessSandbox:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = Path(sys.executable).resolve()
    policy = WorkspaceResourcePolicy(workspace, allowed_tool_paths=[executable])
    return ProcessSandbox(policy, timeout_seconds=timeout, max_output_chars=256)


def write_script(sandbox: ProcessSandbox, name: str, content: str) -> Path:
    target = sandbox.policy.workspace_root / name
    target.write_text(content, encoding="utf-8")
    sandbox.policy.validate_workspace_path(target)
    return target


def test_runs_explicit_tool_without_shell(tmp_path: Path) -> None:
    sandbox = make_sandbox(tmp_path)
    script = write_script(sandbox, "hello.py", "print('x')\n")
    result = sandbox.run([str(Path(sys.executable).resolve()), script.name])
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
    script = write_script(
        sandbox,
        "env.py",
        "import os\nprint(os.getenv('API_KEY'))\nprint(os.getenv('AGENT_TEST'))\n",
    )
    result = sandbox.run([str(Path(sys.executable).resolve()), script.name], env={"AGENT_TEST": "ok"})
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["None", "ok"]


def test_external_access_must_be_declared(tmp_path: Path) -> None:
    sandbox = make_sandbox(tmp_path)
    script = write_script(sandbox, "hello.py", "print('x')\n")
    with pytest.raises(ProcessSandboxSafetyStop):
        sandbox.run(
            [str(Path(sys.executable).resolve()), script.name],
            external_reads=[tmp_path / "unmanaged" / "data.txt"],
        )


def test_workspace_target_cannot_escape(tmp_path: Path) -> None:
    sandbox = make_sandbox(tmp_path)
    script = write_script(sandbox, "hello.py", "print('x')\n")
    with pytest.raises(ProcessSandboxSafetyStop):
        sandbox.run(
            [str(Path(sys.executable).resolve()), script.name],
            target_paths=["../outside.py"],
        )


def test_timeout_returns_bounded_failure(tmp_path: Path) -> None:
    sandbox = make_sandbox(tmp_path, timeout=0.2)
    script = write_script(sandbox, "sleep.py", "import time\ntime.sleep(5)\n")
    result = sandbox.run([str(Path(sys.executable).resolve()), script.name])
    assert result.timed_out is True
    assert result.returncode == -1
    assert "PROCESS TIMEOUT" in result.stderr


def test_strict_os_mode_fails_closed_until_native_backend_exists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = WorkspaceResourcePolicy(workspace, allowed_tool_paths=[Path(sys.executable).resolve()])
    with pytest.raises(ProcessSandboxSafetyStop):
        ProcessSandbox(policy, containment_mode="strict_os_required")
