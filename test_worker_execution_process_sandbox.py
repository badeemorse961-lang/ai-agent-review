from __future__ import annotations

import sys
from pathlib import Path

import pytest

from process_sandbox import ProcessSandbox, ProcessSandboxSafetyStop
from sandbox_policy import ExternalResource, WorkspaceResourcePolicy
from worker_execution import WorkerExecutionBoundary


def build_boundary(
    tmp_path: Path,
    *,
    external_resources: list[ExternalResource] | None = None,
) -> tuple[WorkerExecutionBoundary, Path, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    script = workspace / "worker.py"
    executable = Path(sys.executable).resolve()
    policy = WorkspaceResourcePolicy(
        workspace,
        allowed_tool_paths=[executable],
        external_resources=external_resources or [],
    )
    process_sandbox = ProcessSandbox(policy, timeout_seconds=3)
    boundary = WorkerExecutionBoundary(
        workspace,
        checkpoint=lambda request: {
            "isolated": True,
            "task_id": request.task_id,
        },
        process_sandbox=process_sandbox,
        timeout_seconds=3,
    )
    return boundary, script, executable


def test_worker_can_use_approved_external_tool_with_process_sandbox(tmp_path: Path) -> None:
    boundary, script, executable = build_boundary(tmp_path)
    script.write_text("print('worker-ok')\n", encoding="utf-8")

    result = boundary.execute(
        {
            "task_id": "task-1",
            "role": "coder",
            "worker_id": "coder-01",
        },
        {
            "task_id": "task-1",
            "role": "coder",
            "acceptance_criteria": ["script executes successfully"],
        },
        command=[str(executable), script.name],
        targets=[script.name],
    )

    assert result.succeeded
    assert result.stdout.strip() == "worker-ok"


def test_worker_can_read_explicit_external_resource(tmp_path: Path) -> None:
    external = tmp_path / "design-assets"
    external.mkdir()
    asset = external / "asset.txt"
    asset.write_text("asset-ok\n", encoding="utf-8")

    boundary, script, executable = build_boundary(
        tmp_path,
        external_resources=[ExternalResource(str(external), "read", "design-assets")],
    )
    script.write_text(
        f"from pathlib import Path\nprint(Path(r'{asset}').read_text(encoding='utf-8').strip())\n",
        encoding="utf-8",
    )

    result = boundary.execute(
        {
            "task_id": "task-2",
            "role": "coder",
            "worker_id": "coder-01",
        },
        {
            "task_id": "task-2",
            "role": "coder",
            "acceptance_criteria": ["external asset can be read"],
        },
        command=[str(executable), script.name],
        targets=[script.name],
        external_reads=[str(asset)],
    )

    assert result.succeeded
    assert result.stdout.strip() == "asset-ok"


def test_worker_cannot_claim_undeclared_external_resource(tmp_path: Path) -> None:
    external = tmp_path / "outside"
    external.mkdir()
    script_target = external / "asset.txt"
    script_target.write_text("nope", encoding="utf-8")

    boundary, script, executable = build_boundary(tmp_path)
    script.write_text("print('worker-ok')\n", encoding="utf-8")

    with pytest.raises(ProcessSandboxSafetyStop):
        boundary.execute(
            {
                "task_id": "task-3",
                "role": "coder",
                "worker_id": "coder-01",
            },
            {
                "task_id": "task-3",
                "role": "coder",
                "acceptance_criteria": ["undeclared external resource is rejected"],
            },
            command=[str(executable), script.name],
            targets=[script.name],
            external_reads=[str(script_target)],
        )
