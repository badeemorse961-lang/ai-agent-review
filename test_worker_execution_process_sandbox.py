from __future__ import annotations

import sys
from pathlib import Path

from process_sandbox import ProcessSandbox
from sandbox_policy import WorkspaceResourcePolicy
from worker_execution import WorkerExecutionBoundary


def test_worker_can_use_approved_external_tool_with_process_sandbox(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    script = workspace / "worker.py"
    script.write_text("print('worker-ok')\n", encoding="utf-8")

    executable = Path(sys.executable).resolve()
    policy = WorkspaceResourcePolicy(workspace, allowed_tool_paths=[executable])
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
