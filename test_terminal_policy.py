from __future__ import annotations

from pathlib import Path

import pytest

from process_sandbox import ProcessSandboxSafetyStop
from terminal_policy import TerminalCommandPolicy, TerminalPolicy


def test_python_workspace_command_is_allowed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    policy = TerminalPolicy()

    command = policy.validate(
        ["python", "worker.py"],
        workspace_root=workspace,
    )

    assert command == ("python", "worker.py")


def test_python_inline_execution_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ProcessSandboxSafetyStop):
        TerminalPolicy().validate(
            ["python", "-c", "print('no')"],
            workspace_root=workspace,
        )


def test_unknown_executable_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(ProcessSandboxSafetyStop):
        TerminalPolicy().validate(
            ["curl", "https://example.com"],
            workspace_root=workspace,
        )


def test_git_uses_dedicated_safety_policy_even_when_terminal_policy_is_custom() -> None:
    policy = TerminalPolicy(
        [TerminalCommandPolicy("git", allowed_subcommands=("status", "diff"))]
    )
    workspace = Path.cwd()

    assert policy.validate(["git", "status"], workspace_root=workspace) == (
        "git",
        "status",
    )

    with pytest.raises(ProcessSandboxSafetyStop):
        policy.validate(["git", "commit", "-m", "should-not-run"], workspace_root=workspace)

    with pytest.raises(ProcessSandboxSafetyStop):
        policy.validate(["git", "push"], workspace_root=workspace)


def test_external_path_argument_requires_read_authority(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "assets"
    external.mkdir()
    asset = external / "asset.txt"
    asset.write_text("ok", encoding="utf-8")

    policy = TerminalPolicy()

    with pytest.raises(ProcessSandboxSafetyStop):
        policy.validate(
            ["python", str(asset)],
            workspace_root=workspace,
        )

    allowed = policy.validate(
        ["python", str(asset)],
        workspace_root=workspace,
        external_reads={external: "read"},
    )
    assert allowed == ("python", str(asset))


def test_write_only_external_resource_cannot_be_used_as_command_input(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "assets"
    external.mkdir()
    asset = external / "asset.txt"
    asset.write_text("ok", encoding="utf-8")

    with pytest.raises(ProcessSandboxSafetyStop):
        TerminalPolicy().validate(
            ["python", str(asset)],
            workspace_root=workspace,
            external_reads={external: "write"},
        )
