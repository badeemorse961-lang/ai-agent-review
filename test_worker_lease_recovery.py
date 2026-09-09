from __future__ import annotations

from pathlib import Path

import pytest

from durable_execution_evidence import EvidenceLayer
from durable_execution_state import DurableExecutionState, InvalidTransitionError, LineageError, RecoveryAmbiguityError, StateConflictError
from test_orchestration_durable import build_durable_orchestrator
from worker_lease_recovery import WorkerLeaseRecovery


def lifecycle(tmp_path: Path, name: str = "db.sqlite3"):
    root = tmp_path / "project"
    root.mkdir()
    orchestrator, state, _, _ = build_durable_orchestrator(root, tmp_path / name)
    bridge = orchestrator._durable
    run_id = bridge.create_run()
    bridge.accept_plan(run_id, "GOAL", {"tasks": [{"task_id": "TASK-1"}]})
    phase_id = run_id + ":PHASE:1"
    bridge.start_phase(run_id, phase_id)
    bridge.start_running(run_id)
    task = {"task_id": "TASK-1", "objective": "recovery test", "retry_class": "IDEMPOTENT", "depends_on": []}
    bridge.start_task(run_id, phase_id, task)
    attempt_id = run_id + ":TASK-1:ATTEMPT:1"
    bridge.start_attempt(run_id, phase_id, "TASK-1", attempt_id, "W-1")
    return root, state, bridge, run_id, phase_id, "TASK-1", attempt_id


def bind(state, bridge, run_id, phase_id, task_id, attempt_id, lease_id="LEASE-1"):
    recovery = WorkerLeaseRecovery(state)
    expected = state.get_run(run_id, project_id=bridge.project_id).sequence
    record = recovery.bind_actual_lease(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, lease_id=lease_id, worker_id="W-1", expected_sequence=expected)
    return recovery, record


def test_lease_lifecycle_release(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path)
    recovery, record = bind(state, bridge, run_id, phase_id, task_id, attempt_id)
    assert record.state == "ACTIVE"
    result = recovery.release(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id)
    assert result.lease_state == "RELEASED"
    assert result.attempt_state == "STARTED"


def test_exact_attempt_lease_lineage(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path)
    recovery = WorkerLeaseRecovery(state)
    with pytest.raises(LineageError):
        recovery.bind_actual_lease(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id="FOREIGN-ATTEMPT", lease_id="LEASE-X", worker_id="W-1", expected_sequence=state.get_run(run_id, project_id=bridge.project_id).sequence)
    recovery.bind_actual_lease(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, lease_id="LEASE-1", worker_id="W-1")
    with pytest.raises(LineageError):
        recovery.release(project_id="FOREIGN-PROJECT", run_id="FOREIGN-RUN", lease_id="LEASE-1")


def test_stale_signal_is_deterministic_and_changes_attempt_task(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path)
    recovery, record = bind(state, bridge, run_id, phase_id, task_id, attempt_id)
    with pytest.raises(ValueError):
        recovery.mark_stale(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="stale-1", stale_signal="TIMEOUT")
    result = recovery.mark_stale(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="stale-1", stale_signal="LEASE_EXPIRED")
    assert result.lease_state == "STALE"
    assert result.attempt_state == "INTERRUPTED"
    assert result.task_state == "INTERRUPTED"
    assert result.recovery_state == "UNKNOWN"


def test_stale_transition_is_idempotent(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path)
    recovery, record = bind(state, bridge, run_id, phase_id, task_id, attempt_id)
    first = recovery.mark_stale(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="stale-idempotent", stale_signal="LEASE_EXPIRED")
    count = len(state.get_events(project_id=bridge.project_id, run_id=run_id))
    second = recovery.mark_stale(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="stale-idempotent", stale_signal="LEASE_EXPIRED")
    assert first.operation_id == second.operation_id
    assert first.lease_state == second.lease_state == "STALE"
    assert count == len(state.get_events(project_id=bridge.project_id, run_id=run_id))


def test_safe_reclaim_requires_explicit_effect_evidence(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path)
    recovery, record = bind(state, bridge, run_id, phase_id, task_id, attempt_id)
    stale = recovery.mark_stale(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="stale-2", stale_signal="EXPLICIT_WORKER_INTERRUPTION")
    assert stale.lease_state == "STALE"
    with pytest.raises(RecoveryAmbiguityError):
        recovery.reclaim(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="reclaim-bad", effect_state="UNKNOWN", effect_reference="effect://unknown", effect_hash="unknown")
    reclaimed = recovery.reclaim(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="reclaim-good", effect_state="NO_EXTERNAL_EFFECT", effect_reference="effect://explicit/no-effect", effect_hash="sha256:explicit-no-effect")
    assert reclaimed.lease_state == "RECLAIMED"
    assert reclaimed.attempt_state == "RECOVERY_REQUIRED"
    assert reclaimed.task_state == "RECOVERY_REQUIRED"
    assert reclaimed.recovery_state == "COMMITTED"


def test_ambiguous_lease_does_not_become_retry_safe(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path)
    recovery, record = bind(state, bridge, run_id, phase_id, task_id, attempt_id)
    ambiguous = recovery.mark_ambiguous(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="amb-1", ambiguity_reason="worker result and external effect cannot be correlated")
    assert ambiguous.lease_state == "AMBIGUOUS"
    assert ambiguous.attempt_state == "AMBIGUOUS"
    assert ambiguous.task_state == "RECOVERY_REQUIRED"
    with pytest.raises(RecoveryAmbiguityError):
        recovery.reclaim(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="reclaim-amb", effect_state="AMBIGUOUS", effect_reference="effect://unknown", effect_hash="hash")


def test_reclaim_is_idempotent_and_operation_durable(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path)
    recovery, record = bind(state, bridge, run_id, phase_id, task_id, attempt_id)
    recovery.mark_stale(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="stale-replay", stale_signal="LEASE_EXPIRED")
    first = recovery.reclaim(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="reclaim-replay", effect_state="EFFECT_EXPLICITLY_RESOLVED", effect_reference="effect://resolved", effect_hash="sha256:resolved")
    before = len(state.get_events(project_id=bridge.project_id, run_id=run_id))
    second = recovery.reclaim(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="reclaim-replay", effect_state="EFFECT_EXPLICITLY_RESOLVED", effect_reference="effect://resolved", effect_hash="sha256:resolved")
    after = len(state.get_events(project_id=bridge.project_id, run_id=run_id))
    assert first.operation_id == second.operation_id
    assert first.idempotency_key == second.idempotency_key
    assert before == after
    state.close()
    reopened = DurableExecutionState(tmp_path / "db.sqlite3")
    row = reopened._connection.execute("SELECT state, operation_id, idempotency_key FROM recovery_operations WHERE idempotency_key=?", ("reclaim-replay",)).fetchone()
    assert row["state"] == "COMMITTED"
    assert row["operation_id"] != row["idempotency_key"]
    reopened.verify_integrity(project_id=bridge.project_id, run_id=run_id)


def test_stale_sequence_is_rejected(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path)
    recovery, record = bind(state, bridge, run_id, phase_id, task_id, attempt_id)
    current = state.get_run(run_id, project_id=bridge.project_id).sequence
    with pytest.raises(StateConflictError):
        recovery.mark_stale(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="stale-fence", stale_signal="LEASE_EXPIRED", expected_sequence=current - 1)


def test_event_hash_chain_contains_recovery_events(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path)
    recovery, record = bind(state, bridge, run_id, phase_id, task_id, attempt_id)
    recovery.mark_stale(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="chain-stale", stale_signal="LEASE_EXPIRED")
    recovery.reclaim(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="chain-reclaim", effect_state="NO_EXTERNAL_EFFECT", effect_reference="effect://chain", effect_hash="sha256:chain")
    event_types = [row["event_type"] for row in state.get_events(project_id=bridge.project_id, run_id=run_id)]
    assert "LEASE_BOUND" in event_types
    assert "LEASE_STALE" in event_types
    assert "LEASE_RECLAIMED" in event_types
    assert "ATTEMPT_INTERRUPTED" in event_types
    assert "ATTEMPT_RECOVERY_REQUIRED" in event_types
    assert "TASK_INTERRUPTED" in event_types
    assert "TASK_RECOVERY_REQUIRED" in event_types
    assert "RECOVERY_OPERATION_STARTED" in event_types
    assert "RECOVERY_OPERATION_UNKNOWN" in event_types
    assert "RECOVERY_OPERATION_COMMITTED" in event_types
    state.verify_integrity(project_id=bridge.project_id, run_id=run_id)


def test_cross_run_cannot_reclaim_foreign_lease(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path, "shared.sqlite3")
    recovery, record = bind(state, bridge, run_id, phase_id, task_id, attempt_id)
    other_root = tmp_path / "other"
    other_root.mkdir()
    other_state = DurableExecutionState(tmp_path / "other.sqlite3")
    other_project = "PROJECT-OTHER"
    other_state.create_project(workspace_root=other_root, project_id=other_project)
    other_run = other_state.create_run(other_project)
    with pytest.raises(LineageError):
        recovery.release(project_id=other_project, run_id=other_run.run_id, lease_id=record.lease_id)
    other_state.close()


def test_completed_task_cannot_acquire_recovery_lease(tmp_path: Path) -> None:
    root = tmp_path / "complete-project"
    root.mkdir()
    orchestrator, state, _, _ = build_durable_orchestrator(root, tmp_path / "complete.sqlite3")
    result = orchestrator.run("GOAL-COMPLETE")
    project_id, run_id, phase_id = result.durable_project_id, result.durable_run_id, result.durable_phase_id
    task_id = result.task_records[0].task["task_id"]
    task = state._connection.execute("SELECT state FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (project_id, run_id, phase_id, task_id)).fetchone()
    assert task["state"] == "COMPLETED"
    attempt_id = f"{run_id}:{task_id}:ATTEMPT:1"
    with pytest.raises(InvalidTransitionError):
        WorkerLeaseRecovery(state).bind_actual_lease(project_id=project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, lease_id="LEASE-COMPLETED", worker_id="W-1")


def test_interrupted_attempt_cannot_complete_without_validation_evidence(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path)
    recovery, record = bind(state, bridge, run_id, phase_id, task_id, attempt_id)
    recovery.mark_stale(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, idempotency_key="no-complete", stale_signal="LEASE_EXPIRED")
    with pytest.raises(InvalidTransitionError):
        EvidenceLayer(state).complete_task(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, validation_id="missing-validation")


def test_release_duplicate_is_idempotent(tmp_path: Path) -> None:
    _, state, bridge, run_id, phase_id, task_id, attempt_id = lifecycle(tmp_path)
    recovery, record = bind(state, bridge, run_id, phase_id, task_id, attempt_id)
    first = recovery.release(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, reason="normal")
    event_count = len(state.get_events(project_id=bridge.project_id, run_id=run_id))
    second = recovery.release(project_id=bridge.project_id, run_id=run_id, lease_id=record.lease_id, reason="normal")
    assert first.operation_id == second.operation_id
    assert event_count == len(state.get_events(project_id=bridge.project_id, run_id=run_id))
