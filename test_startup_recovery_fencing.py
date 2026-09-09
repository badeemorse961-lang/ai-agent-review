from __future__ import annotations

from pathlib import Path

import pytest

from durable_execution_state import StateConflictError
from startup_recovery import StartupRecovery
from test_startup_recovery import _create_running_run


def test_startup_recovery_rejects_stale_run_sequence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, state, bridge, run_id, *_ = _create_running_run(tmp_path)
    original = state.transition_run
    injected = {"done": False}

    def fenced(*, project_id: str, run_id: str, expected_sequence: int, new_state: str, event_type: str, entity_id=None, payload=None):
        if new_state == "RECOVERING" and not injected["done"]:
            injected["done"] = True
            current = state.get_run(run_id, project_id=project_id)
            original(project_id=project_id, run_id=run_id, expected_sequence=current.sequence, new_state="PAUSED", event_type="TEST_CONCURRENT_UPDATE", entity_id=run_id, payload={"source": "deterministic-race-test"})
        return original(project_id=project_id, run_id=run_id, expected_sequence=expected_sequence, new_state=new_state, event_type=event_type, entity_id=entity_id, payload=payload)

    monkeypatch.setattr(state, "transition_run", fenced)
    with pytest.raises(StateConflictError):
        StartupRecovery(state, root).recover()
    assert state.get_run(run_id, project_id=bridge.project_id).state == "PAUSED"
    state.verify_integrity(project_id=bridge.project_id, run_id=run_id)
