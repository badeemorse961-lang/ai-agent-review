from __future__ import annotations

from pathlib import Path

import pytest

from sandbox_policy import (
    ExternalResource,
    SandboxPolicySafetyStop,
    WorkspaceResourcePolicy,
)


def make_policy(tmp_path: Path) -> WorkspaceResourcePolicy:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    tool = tmp_path / "python.exe"
    tool.write_text("tool", encoding="utf-8")
    external = tmp_path / "assets"
    external.mkdir()
    return WorkspaceResourcePolicy(
        workspace,
        allowed_tool_paths=[tool],
        external_resources=[ExternalResource(str(external), "read", "design-assets")],
    )


def test_workspace_path_is_allowed(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    target = policy.validate_workspace_path("src/app.py")
    assert target == (tmp_path / "workspace" / "src" / "app.py").resolve()
    assert policy.classify_path(target) == "workspace"


def test_workspace_escape_is_rejected(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    with pytest.raises(SandboxPolicySafetyStop):
        policy.validate_workspace_path("../outside.txt")


def test_tool_outside_workspace_requires_allowlist(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    tool = tmp_path / "python.exe"
    assert policy.validate_tool_executable(tool) == tool.resolve()

    other = tmp_path / "node.exe"
    other.write_text("tool", encoding="utf-8")
    with pytest.raises(SandboxPolicySafetyStop):
        policy.validate_tool_executable(other)


def test_external_read_requires_explicit_resource(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    allowed = tmp_path / "assets" / "logo.svg"
    denied = tmp_path / "secrets.txt"

    assert policy.validate_external_path(allowed, access="read") == allowed.resolve()
    with pytest.raises(SandboxPolicySafetyStop):
        policy.validate_external_path(denied, access="read")


def test_read_resource_does_not_grant_write(tmp_path: Path) -> None:
    policy = make_policy(tmp_path)
    with pytest.raises(SandboxPolicySafetyStop):
        policy.validate_external_path(tmp_path / "assets" / "logo.svg", access="write")


def test_read_write_resource_grants_both(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "shared"
    external.mkdir()
    policy = WorkspaceResourcePolicy(
        workspace,
        external_resources=[ExternalResource(str(external), "read_write")],
    )
    target = external / "design.png"
    assert policy.validate_external_path(target, access="read") == target.resolve()
    assert policy.validate_external_path(target, access="write") == target.resolve()
