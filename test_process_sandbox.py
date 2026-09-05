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


def write_script(sandbox: ProcessSandbox, name: str, content: str) -> Path:
    target = sandbox.policy.workspace_root / name
    target.write_text(content, encoding="utf-8")
    sandbox.policy.validate_workspace_path(target)
    return target


def test_runs_explicit_tool_without_shell(tmp_path: Path) -> None:
    sandbox = make_sandbox(tmp_path)
    script = write_script(sandbox, "hello.py", "print('x')\n")
    result = sandbox.run([str(Path(sys.executable).resolve()), str(script.name)])
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


def test_strict_os_mode_fails_closed_until_native_backend_exists(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = WorkspaceResourcePolicy(workspace, allowed_tool_paths=[Path(sys.executable).resolve()])
    with pytest.raises(ProcessSandboxSafetyStop):
        ProcessSandbox(policy, containment_mode="strict_os_required")
