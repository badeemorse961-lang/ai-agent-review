from __future__ import annotations

import sys
from pathlib import Path

import pytest

from process_sandbox import ProcessSandbox, ProcessSandboxSafetyStop
from sandbox_policy import ExternalResource, WorkspaceResourcePolicy
from terminal_executor import TerminalExecutor


def build_executor(tmp_path: Path) -> tuple[TerminalExecutor, Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = Path(sys.executable).resolve()
    policy = WorkspaceResourcePolicy(
        workspace,
        allowed_tool_paths=[executable],
    )
    sandbox = ProcessSandbox(policy, timeout_seconds=3)
    return TerminalExecutor(sandbox), workspace, executable


def test_terminal_executor_runs_approved_workspace_script(tmp_path: Path) -> None:
    executor, workspace, executable = build_executor(tmp_path)
    script = workspace / "worker.py"
    script.write_text("print('terminal-ok')\n", encoding="utf-8")

    result = executor.run(
        [str(executable), script.name],
        target_paths=[script.name],
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "terminal-ok"
    assert not result.timed_out


def test_terminal_executor_rejects_inline_python(tmp_path: Path) -> None:
    executor, _, executable = build_executor(tmp_path)

    with pytest.raises(ProcessSandboxSafetyStop):
        executor.run([str(executable), "-c", "print('blocked')"])


def test_terminal_executor_blocks_git_mutation_before_process_launch(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    executable = Path(sys.executable).resolve()
    sandbox = ProcessSandbox(
        WorkspaceResourcePolicy(workspace, allowed_tool_paths=[executable]),
        timeout_seconds=3,
    )
    executor = TerminalExecutor(sandbox)

    with pytest.raises(ProcessSandboxSafetyStop):
        executor.run(["git", "commit", "-m", "must-not-run"])


def test_terminal_executor_preserves_explicit_external_read_boundary(tmp_path: Path) -> None:
    external = tmp_path / "assets"
    external.mkdir()
    asset = external / "asset.txt"
    asset.write_text("external-ok\n", encoding="utf-8")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executable = Path(sys.executable).resolve()
    policy = WorkspaceResourcePolicy(
        workspace,
        allowed_tool_paths=[executable],
        external_resources=[ExternalResource(str(external), "read", "assets")],
    )
    executor = TerminalExecutor(ProcessSandbox(policy, timeout_seconds=3))
    script = workspace / "read_asset.py"
    script.write_text(
        f"from pathlib import Path\nprint(Path(r'{asset}').read_text(encoding='utf-8').strip())\n",
        encoding="utf-8",
    )

    result = executor.run(
        [str(executable), script.name],
        target_paths=[script.name],
        external_reads=[str(asset)],
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "external-ok"
