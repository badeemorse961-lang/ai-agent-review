from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from execution_gate import FileChange
from orchestration import WorkerExecutionSpec
from test_orchestration import make_orchestrator, workspace
from worker_work_product import WorkerWorkProduct


class ProtocolWorkerAdapter:
    def __init__(self) -> None:
        self.prepared = 0

    def prepare(self, task: Mapping[str, Any], assignment: Mapping[str, Any]) -> WorkerWorkProduct:
        self.prepared += 1
        return WorkerWorkProduct(
            task_id=str(task["task_id"]),
            worker_id=str(assignment["worker_id"]),
            role=str(task["role"]),
            command=("pytest", "-q", "test_target.py"),
            targets=("test_target.py",),
            changed_targets=("target.txt",),
            changes=(FileChange("target.txt", 'VALUE = "before"', 'VALUE = "after"'),),
            validation_evidence={"criteria": ["tests pass"]},
            status="READY",
        )

    def validate(
        self,
        request: Any,
        task: Mapping[str, Any],
        result: Any,
        spec: WorkerExecutionSpec,
    ) -> Mapping[str, Any]:
        del request, task, result, spec
        return {"passed": True}


def test_canonical_orchestration_accepts_authoritative_work_product(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    adapter = ProtocolWorkerAdapter()
    orchestrator, *_ = make_orchestrator(root, worker_adapter=adapter)  # type: ignore[arg-type]
    result = orchestrator.run("TASK-PROTOCOL")
    assert result.status == "APPROVED"
    assert adapter.prepared == 1
    record = result.task_records[0]
    assert record.work_product["schema_version"] == 1
    assert record.work_product["task_id"] == "TASK-PROTOCOL:1"
    assert record.work_product["mutation"]["changed_targets"] == ["target.txt"]
