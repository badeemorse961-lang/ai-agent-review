from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from durable_execution_evidence import EvidenceLayer
from durable_execution_state import DurableExecutionState, LineageError
from startup_recovery import StartupRecovery, StartupRecoverySafetyStop
from test_orchestration_durable import build_durable_orchestrator
from worker_lease_recovery import WorkerLeaseRecovery


def _project_id(root: Path) -> str:
    return "PROJECT-" + hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:24]


def _create_running_run(tmp_path: Path, db_name: str = "execution.sqlite3"):
    root = tmp_path / "project"
    root.mkdir()
    orchestrator, state, _, _ = build_durable_orchestrator(root, tmp_path / db_name)
    bridge = orchestrator._durable
    run_id = bridge.create_run()
    bridge.accept_plan(run_id, "GOAL", {"tasks": [{"task_id": "TASK-1"}]})
    phase_id = run_id + ":PHASE:1"
    bridge.start_phase(run_id, phase_id)
    bridge.start_running(run_id)
    task = {"task_id": "TASK-1", "objective": "startup recovery", "retry_class": "IDEMPOTENT", "depends_on": []}
    bridge.start_task(run_id, phase_id, task)
    attempt_id = run_id + ":TASK-1:ATTEMPT:1"
    bridge.start_attempt(run_id, phase_id, "TASK-1", attempt_id, "W-1")
    return root, state, bridge, run_id, phase_id, "TASK-1", attempt_id


def _bind_active(state, bridge, run_id, phase_id, task_id, attempt_id, lease_id="LEASE-1"):
    recovery = WorkerLeaseRecovery(state)
    return recovery.bind_actual_lease(
        project_id=bridge.project_id,
        run_id=run_id,
        phase_id=phase_id,
        task_id=task_id,
        attempt_id=attempt_id,
        lease_id=lease_id,
        worker_id="W-1",
    )


def test_startup_discovers_running_run_and_persists_recovery_decision(tmp_path: Path) -> None:
    root, state, bridge, run_id, phase_id, task_id, attempt_id = _create_running_run(tmp_path)
    before = state.get_run(run_id, project_id=bridge.project_id).state
    report = StartupRecovery(state, root).recover()
    assert before == "RUNNING"
    assert report.discovered_runs == (run_id,)
    run = state.get_run(run_id, project_id=bridge.project_id)
    assert run.state == "RECOVERY_REQUIRED"
    operation = state._connection.execute("SELECT operation_kind, idempotency_key, state, effect_reference FROM recovery_operations WHERE project_id=? AND run_id=?", (bridge.project_id, run_id)).fetchone()
    assert operation["operation_kind"] == "STARTUP_INTERRUPTED_RUN_DISCOVERY"
    assert operation["idempotency_key"].startswith("startup-recovery:v1:")
    assert operation["state"] == "UNKNOWN"
    assert "effect_state=UNKNOWN" in operation["effect_reference"]
    assert state._connection.execute("SELECT state FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (bridge.project_id, run_id, phase_id, task_id)).fetchone()[0] == "IN_PROGRESS"
    state.verify_integrity(project_id=bridge.project_id, run_id=run_id)
    assert attempt_id


def test_startup_discovers_interrupted_task(tmp_path: Path) -> None:
    root, state, bridge, run_id, phase_id, task_id, attempt_id = _create_running_run(tmp_path)
    _bind_active(state, bridge, run_id, phase_id, task_id, attempt_id)
    recovery = WorkerLeaseRecovery(state)
    recovery.mark_stale(project_id=bridge.project_id, run_id=run_id, lease_id="LEASE-1", idempotency_key="m4-stale", stale_signal="LEASE_EXPIRED")
    report = StartupRecovery(state, root).recover()
    assert run_id in report.discovered_runs
    task = state._connection.execute("SELECT state FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (bridge.project_id, run_id, phase_id, task_id)).fetchone()
    attempt = state._connection.execute("SELECT state FROM attempts WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (bridge.project_id, run_id, phase_id, task_id, attempt_id)).fetchone()
    assert task[0] in {"INTERRUPTED", "RECOVERY_REQUIRED"}
    assert attempt[0] in {"INTERRUPTED", "RECOVERY_REQUIRED"}


def test_startup_active_lease_becomes_ambiguous_without_timeout_inference(tmp_path: Path) -> None:
    root, state, bridge, run_id, phase_id, task_id, attempt_id = _create_running_run(tmp_path)
    _bind_active(state, bridge, run_id, phase_id, task_id, attempt_id)
    report = StartupRecovery(state, root).recover()
    assert run_id in report.discovered_runs
    lease = state._connection.execute("SELECT state FROM lease_bindings WHERE lease_id=?", ("LEASE-1",)).fetchone()
    attempt = state._connection.execute("SELECT state FROM attempts WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (bridge.project_id, run_id, phase_id, task_id, attempt_id)).fetchone()
    task = state._connection.execute("SELECT state FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (bridge.project_id, run_id, phase_id, task_id)).fetchone()
    assert lease[0] == "AMBIGUOUS"
    assert attempt[0] == "AMBIGUOUS"
    assert task[0] == "RECOVERY_REQUIRED"
    recovery_op = state._connection.execute("SELECT state FROM recovery_operations WHERE idempotency_key=?", (f"startup-lease-ambiguity:v1:{bridge.project_id}:{run_id}:LEASE-1",)).fetchone()
    assert recovery_op[0] == "UNKNOWN"


def test_startup_twice_is_idempotent(tmp_path: Path) -> None:
    root, state, bridge, run_id, phase_id, task_id, attempt_id = _create_running_run(tmp_path)
    _bind_active(state, bridge, run_id, phase_id, task_id, attempt_id)
    recovery = StartupRecovery(state, root)
    first = recovery.recover()
    event_count = len(state.get_events(project_id=bridge.project_id, run_id=run_id))
    operation_count = state._connection.execute("SELECT COUNT(*) FROM recovery_operations WHERE project_id=? AND run_id=?", (bridge.project_id, run_id)).fetchone()[0]
    second = recovery.recover()
    assert first == second
    assert len(state.get_events(project_id=bridge.project_id, run_id=run_id)) == event_count
    assert state._connection.execute("SELECT COUNT(*) FROM recovery_operations WHERE project_id=? AND run_id=?", (bridge.project_id, run_id)).fetchone()[0] == operation_count
    assert state._connection.execute("SELECT COUNT(*) FROM tasks WHERE project_id=? AND run_id=? AND state='COMPLETED'", (bridge.project_id, run_id)).fetchone()[0] == 0
    assert attempt_id


def test_startup_sequence_fence_rejects_stale_run_write(tmp_path: Path) -> None:
    root, state, bridge, run_id, phase_id, task_id, attempt_id = _create_running_run(tmp_path)
    current = state.get_run(run_id, project_id=bridge.project_id)
    state.transition_run(project_id=bridge.project_id, run_id=run_id, expected_sequence=current.sequence, new_state="PAUSED", event_type="TEST_PAUSE")
    with pytest.raises(Exception):
        state.transition_run(project_id=bridge.project_id, run_id=run_id, expected_sequence=current.sequence, new_state="RECOVERING", event_type="STALE_STARTUP_RECOVERY")
    assert state.get_run(run_id, project_id=bridge.project_id).state == "PAUSED"
    assert attempt_id and phase_id and task_id


def test_corrupt_event_chain_blocks_safe_recovery(tmp_path: Path) -> None:
    root, state, bridge, run_id, *_ = _create_running_run(tmp_path)
    state._connection.execute("UPDATE execution_events SET payload_json=? WHERE project_id=? AND run_id=? AND sequence=1", ('{"project_id":"tampered"}', bridge.project_id, run_id))
    with pytest.raises(StartupRecoverySafetyStop):
        StartupRecovery(state, root).recover()


def test_project_workspace_mismatch_blocks_recovery(tmp_path: Path) -> None:
    root = tmp_path / "active"
    root.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    db = tmp_path / "execution.sqlite3"
    state = DurableExecutionState(db)
    project_id = _project_id(root)
    state.create_project(workspace_root=other, project_id=project_id)
    with pytest.raises(StartupRecoverySafetyStop):
        StartupRecovery(state, root).recover()


def test_cross_project_isolation(tmp_path: Path) -> None:
    root_a = tmp_path / "project-a"
    root_a.mkdir()
    root_b = tmp_path / "project-b"
    root_b.mkdir()
    db = tmp_path / "shared.sqlite3"
    state = DurableExecutionState(db)
    project_a = _project_id(root_a)
    project_b = _project_id(root_b)
    state.create_project(workspace_root=root_a, project_id=project_a)
    state.create_project(workspace_root=root_b, project_id=project_b)
    run_a = state.create_run(project_a)
    state.transition_run(project_id=project_a, run_id=run_a.run_id, expected_sequence=run_a.sequence, new_state="PLAN_ACCEPTED")
    run_b = state.create_run(project_b)
    state.transition_run(project_id=project_b, run_id=run_b.run_id, expected_sequence=run_b.sequence, new_state="PLAN_ACCEPTED")
    running_b = state.get_run(run_b.run_id, project_id=project_b)
    state.transition_run(project_id=project_b, run_id=run_b.run_id, expected_sequence=running_b.sequence, new_state="RUNNING")
    report = StartupRecovery(state, root_a).recover()
    assert report.discovered_runs == (run_a.run_id,)
    assert state.get_run(run_a.run_id, project_id=project_a).state == "RECOVERY_REQUIRED"
    assert state.get_run(run_b.run_id, project_id=project_b).state == "RUNNING"


def test_ambiguous_effect_never_authorizes_retry(tmp_path: Path) -> None:
    root, state, bridge, run_id, phase_id, task_id, attempt_id = _create_running_run(tmp_path)
    lease = _bind_active(state, bridge, run_id, phase_id, task_id, attempt_id)
    WorkerLeaseRecovery(state).mark_ambiguous(project_id=bridge.project_id, run_id=run_id, lease_id=lease.lease_id, idempotency_key="ambiguous-startup", ambiguity_reason="external result unresolved")
    StartupRecovery(state, root).recover()
    row = state._connection.execute("SELECT state FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (bridge.project_id, run_id, phase_id, task_id)).fetchone()
    assert row[0] == "RECOVERY_REQUIRED"
    assert EvidenceLayer(state).task_completion_ready(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, validation_id="missing") is False


def test_midway_recovery_operation_is_completed_to_unknown_safely(tmp_path: Path) -> None:
    root, state, bridge, run_id, *_ = _create_running_run(tmp_path)
    op = EvidenceLayer(state).create_recovery_operation(project_id=bridge.project_id, run_id=run_id, operation_kind="STARTUP_INTERRUPTED_RUN_DISCOVERY", idempotency_key=f"startup-midway:{run_id}")
    EvidenceLayer(state).transition_recovery_operation(project_id=bridge.project_id, run_id=run_id, operation_id=op.operation_id, new_state="STARTED")
    StartupRecovery(state, root).recover()
    row = state._connection.execute("SELECT state FROM recovery_operations WHERE operation_id=?", (op.operation_id,)).fetchone()
    assert row[0] == "UNKNOWN"
    state.verify_integrity(project_id=bridge.project_id, run_id=run_id)


def test_completed_run_is_not_a_recovery_candidate(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    state = DurableExecutionState(tmp_path / "execution.sqlite3")
    project_id = _project_id(root)
    state.create_project(workspace_root=root, project_id=project_id)
    run = state.create_run(project_id)
    run = state.transition_run(project_id=project_id, run_id=run.run_id, expected_sequence=run.sequence, new_state="PLAN_ACCEPTED")
    run = state.transition_run(project_id=project_id, run_id=run.run_id, expected_sequence=run.sequence, new_state="RUNNING")
    state.transition_run(project_id=project_id, run_id=run.run_id, expected_sequence=run.sequence, new_state="COMPLETED")
    report = StartupRecovery(state, root).recover()
    assert report.discovered_runs == ()
    assert state._connection.execute("SELECT COUNT(*) FROM recovery_operations WHERE project_id=? AND run_id=?", (project_id, run.run_id)).fetchone()[0] == 0


def test_completed_task_is_not_reclaimed_by_startup(tmp_path: Path) -> None:
    root, state, bridge, run_id, phase_id, task_id, attempt_id = _create_running_run(tmp_path)
    state._connection.execute("UPDATE tasks SET state='COMPLETED' WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (bridge.project_id, run_id, phase_id, task_id))
    state._connection.execute("UPDATE attempts SET state='VALIDATED' WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (bridge.project_id, run_id, phase_id, task_id, attempt_id))
    report = StartupRecovery(state, root).recover()
    assert report.discovered_runs == (run_id,)
    assert state._connection.execute("SELECT state FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (bridge.project_id, run_id, phase_id, task_id)).fetchone()[0] == "COMPLETED"
    assert state._connection.execute("SELECT COUNT(*) FROM recovery_operations WHERE project_id=? AND run_id=? AND task_id=?", (bridge.project_id, run_id, task_id)).fetchone()[0] == 1


def test_recovery_never_bypasses_completion_gate(tmp_path: Path) -> None:
    root, state, bridge, run_id, phase_id, task_id, attempt_id = _create_running_run(tmp_path)
    StartupRecovery(state, root).recover()
    task = state._connection.execute("SELECT state FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (bridge.project_id, run_id, phase_id, task_id)).fetchone()
    assert task[0] == "IN_PROGRESS"
    assert EvidenceLayer(state).task_completion_ready(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, validation_id="no-validation") is False


def test_state_survives_close_reopen_and_second_startup(tmp_path: Path) -> None:
    root, state, bridge, run_id, phase_id, task_id, attempt_id = _create_running_run(tmp_path)
    _bind_active(state, bridge, run_id, phase_id, task_id, attempt_id)
    StartupRecovery(state, root).recover()
    operation_count = state._connection.execute("SELECT COUNT(*) FROM recovery_operations WHERE project_id=? AND run_id=?", (bridge.project_id, run_id)).fetchone()[0]
    event_count = len(state.get_events(project_id=bridge.project_id, run_id=run_id))
    db = state.database_path
    project_id = bridge.project_id
    state.close()
    reopened = DurableExecutionState(db)
    second = StartupRecovery(reopened, root).recover()
    assert second.discovered_runs == (run_id,)
    assert reopened.get_run(run_id, project_id=project_id).state == "RECOVERY_REQUIRED"
    assert reopened._connection.execute("SELECT COUNT(*) FROM recovery_operations WHERE project_id=? AND run_id=?", (project_id, run_id)).fetchone()[0] == operation_count
    assert len(reopened.get_events(project_id=project_id, run_id=run_id)) == event_count
    reopened.verify_integrity(project_id=project_id, run_id=run_id)
