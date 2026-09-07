from __future__ import annotations

from pathlib import Path

import pytest

from execution_gate import FileChange
from worker_execution import ExecutionRequest, ExecutionResult
from worker_work_product import WorkerWorkProduct, WorkerWorkProductError


def request(tmp_path: Path) -> ExecutionRequest:
    return ExecutionRequest(
        task_id="TASK-1",
        role="coder",
        worker_id="W-1",
        workspace_root=str(tmp_path.resolve()),
        command=("python", "script.py"),
        targets=("script.py",),
        timeout_seconds=30.0,
    )


def result() -> ExecutionResult:
    return ExecutionResult(
        returncode=0,
        stdout="secret-like raw output must not be copied",
        stderr="",
        timed_out=False,
        truncated=False,
        checkpoint={"isolated": True, "checkpoint_id": "TASK-1:cp"},
    )


def task() -> dict[str, object]:
    return {
        "task_id": "TASK-1",
        "role": "coder",
        "acceptance_criteria": ["tests pass"],
    }


def assignment() -> dict[str, object]:
    return {
        "task_id": "TASK-1",
        "role": "coder",
        "worker_id": "W-1",
        "standby": False,
    }


def change() -> FileChange:
    return FileChange("script.py", "before", "after")


def test_validated_work_product_binds_identity_change_and_checkpoint(tmp_path: Path) -> None:
    product = WorkerWorkProduct.from_validated_execution(
        task=task(),
        assignment=assignment(),
        request=request(tmp_path),
        result=result(),
        changes=(change(),),
        changed_targets=("script.py",),
        validation_evidence={"passed": True, "checkpoint_id": "TASK-1:cp", "test": "PASS"},
    )

    payload = product.to_dict()
    assert product.status == "SUCCEEDED"
    assert payload["task_id"] == "TASK-1"
    assert payload["worker_id"] == "W-1"
    assert payload["command"] == ["python", "script.py"]
    assert payload["changed_targets"] == ["script.py"]
    assert payload["changes"] == [{"path": "script.py", "old_text": "before", "new_text": "after"}]
    assert payload["execution_result"]["checkpoint_id"] == "TASK-1:cp"
    assert "stdout" not in payload["execution_result"]
    assert "secret-like raw output must not be copied" not in str(payload)


def test_changed_targets_must_match_file_changes(tmp_path: Path) -> None:
    with pytest.raises(WorkerWorkProductError, match="exactly match"):
        WorkerWorkProduct.from_validated_execution(
            task=task(),
            assignment=assignment(),
            request=request(tmp_path),
            result=result(),
            changes=(change(),),
            changed_targets=("other.py",),
            validation_evidence={"passed": True, "checkpoint_id": "TASK-1:cp"},
        )


def test_validation_evidence_checkpoint_is_bound(tmp_path: Path) -> None:
    with pytest.raises(WorkerWorkProductError, match="checkpoint_id"):
        WorkerWorkProduct.from_validated_execution(
            task=task(),
            assignment=assignment(),
            request=request(tmp_path),
            result=result(),
            changes=(),
            changed_targets=(),
            validation_evidence={"passed": True, "checkpoint_id": "WRONG"},
        )


def test_validation_must_pass_for_authoritative_success_product(tmp_path: Path) -> None:
    with pytest.raises(WorkerWorkProductError, match="passed=True"):
        WorkerWorkProduct.from_validated_execution(
            task=task(),
            assignment=assignment(),
            request=request(tmp_path),
            result=result(),
            changes=(),
            changed_targets=(),
            validation_evidence={"passed": False, "checkpoint_id": "TASK-1:cp"},
        )


def test_failed_execution_product_has_bounded_failure_state(tmp_path: Path) -> None:
    failed = ExecutionResult(
        returncode=7,
        stdout="sensitive output",
        stderr="also sensitive",
        timed_out=False,
        truncated=False,
        checkpoint={"isolated": True, "checkpoint_id": "TASK-1:cp"},
    )
    product = WorkerWorkProduct.from_failed_execution(
        task=task(),
        assignment=assignment(),
        request=request(tmp_path),
        result=failed,
        reason="worker command failed",
    )

    assert product.status == "FAILED"
    assert product.failure is not None
    assert product.failure.code == "EXECUTION_FAILED"
    assert product.failure.returncode == 7
    assert "sensitive output" not in str(product.to_dict())


def test_timeout_or_truncation_is_safe_stop(tmp_path: Path) -> None:
    stopped = ExecutionResult(
        returncode=1,
        stdout="",
        stderr="",
        timed_out=True,
        truncated=False,
        checkpoint={"isolated": True, "checkpoint_id": "TASK-1:cp"},
    )
    product = WorkerWorkProduct.from_failed_execution(
        task=task(),
        assignment=assignment(),
        request=request(tmp_path),
        result=stopped,
    )

    assert product.status == "SAFE_STOP"
    assert product.failure is not None
    assert product.failure.code == "EXECUTION_SAFE_STOP"
