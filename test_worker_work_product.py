from __future__ import annotations

from execution_gate import FileChange
from worker_work_product import WorkerWorkProduct, WorkerWorkProductError


def product(**overrides):
    values = {
        "task_id": "TASK-1",
        "worker_id": "W-1",
        "role": "coder",
        "command": ("pytest", "-q", "test_target.py"),
        "targets": ("test_target.py",),
        "changed_targets": ("target.txt",),
        "changes": (FileChange("target.txt", "before", "after"),),
        "validation_evidence": {"criteria": ["tests pass"]},
        "status": "READY",
    }
    values.update(overrides)
    return WorkerWorkProduct(**values)


def test_worker_work_product_round_trip_is_deterministic() -> None:
    original = product()
    encoded = original.to_dict()
    restored = WorkerWorkProduct.from_dict(encoded)
    assert restored == original
    assert restored.to_dict() == encoded


def test_identity_mismatch_is_rejected() -> None:
    try:
        product().validate(task_id="WRONG", worker_id="W-1", role="coder")
    except WorkerWorkProductError as exc:
        assert "task identity" in str(exc)
    else:
        raise AssertionError("identity mismatch was accepted")


def test_changed_target_set_must_match_file_changes() -> None:
    value = product(changed_targets=("other.txt",))
    try:
        value.to_dict()
    except WorkerWorkProductError as exc:
        assert "exactly match" in str(exc)
    else:
        raise AssertionError("mismatched mutation set was accepted")


def test_failed_product_requires_structured_failure() -> None:
    try:
        product(status="FAILED")
    except WorkerWorkProductError as exc:
        assert "failure information" in str(exc)
    else:
        raise AssertionError("failed product without failure was accepted")


def test_unknown_schema_is_rejected_before_conversion() -> None:
    payload = product().to_dict()
    payload["schema_version"] = 999
    try:
        WorkerWorkProduct.from_dict(payload)
    except WorkerWorkProductError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("unknown schema was accepted")
