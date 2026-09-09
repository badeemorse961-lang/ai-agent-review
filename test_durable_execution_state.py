from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from durable_execution_state import (
    DurableExecutionState,
    IntegrityError,
    InvalidTransitionError,
    LineageError,
    StateConflictError,
    WorkspaceEvidence,
    utc_now,
)


def make_state(tmp_path: Path) -> DurableExecutionState:
    return DurableExecutionState(tmp_path / ".agent_state" / "execution_state.sqlite3")


def seed_lineage(state: DurableExecutionState, tmp_path: Path) -> tuple[str, str, str, str]:
    project_id = state.create_project(workspace_root=tmp_path / "workspace", project_id="PROJECT-A")
    run = state.create_run(project_id, run_id="RUN-A")
    state.create_phase(project_id=project_id, run_id=run.run_id, phase_id="PHASE-A", ordinal=1, name="phase")
    state.create_task(
        project_id=project_id,
        run_id=run.run_id,
        phase_id="PHASE-A",
        task_id="TASK-A",
        retry_class="IDEMPOTENT",
    )
    attempt_id = state.create_attempt(
        project_id=project_id,
        run_id=run.run_id,
        phase_id="PHASE-A",
        task_id="TASK-A",
        attempt_id="ATTEMPT-A",
        worker_id="W-A",
        lease_id="LEASE-A",
    )
    return project_id, run.run_id, "PHASE-A", attempt_id


def test_project_and_run_survive_new_process_object(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = DurableExecutionState(tmp_path / ".agent_state" / "execution_state.sqlite3")
    project_id = state.create_project(workspace_root=workspace, project_id="PROJECT-A")
    created = state.create_run(project_id, run_id="RUN-A")
    state.close()

    reloaded = DurableExecutionState(tmp_path / ".agent_state" / "execution_state.sqlite3")
    loaded = reloaded.get_run("RUN-A", project_id="PROJECT-A")

    assert loaded.run_id == created.run_id
    assert loaded.project_id == project_id
    assert loaded.sequence == 1
    reloaded.verify_integrity(project_id="PROJECT-A", run_id="RUN-A")


def test_schema_contains_required_unique_lineage_keys(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    rows = state._connection.execute("PRAGMA index_list('runs')").fetchall()
    run_indexes = []
    for row in rows:
        if int(row[2]):
            columns = state._connection.execute(f"PRAGMA index_info('{row[1]}')").fetchall()
            run_indexes.append(tuple(item[2] for item in columns))
    assert ("project_id", "run_id") in run_indexes

    rows = state._connection.execute("PRAGMA index_list('phases')").fetchall()
    phase_indexes = []
    for row in rows:
        if int(row[2]):
            columns = state._connection.execute(f"PRAGMA index_info('{row[1]}')").fetchall()
            phase_indexes.append(tuple(item[2] for item in columns))
    assert ("project_id", "run_id", "phase_id") in phase_indexes

    rows = state._connection.execute("PRAGMA index_list('tasks')").fetchall()
    task_indexes = []
    for row in rows:
        if int(row[2]):
            columns = state._connection.execute(f"PRAGMA index_info('{row[1]}')").fetchall()
            task_indexes.append(tuple(item[2] for item in columns))
    assert ("project_id", "run_id", "phase_id", "task_id") in task_indexes

    rows = state._connection.execute("PRAGMA index_list('attempts')").fetchall()
    attempt_indexes = []
    for row in rows:
        if int(row[2]):
            columns = state._connection.execute(f"PRAGMA index_info('{row[1]}')").fetchall()
            attempt_indexes.append(tuple(item[2] for item in columns))
    assert ("project_id", "run_id", "phase_id", "task_id", "attempt_id") in attempt_indexes


def test_sequence_fence_rejects_stale_writer(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    project_id, run_id, _, _ = seed_lineage(state, tmp_path)
    run = state.get_run(run_id, project_id=project_id)

    advanced = state.transition_run(
        project_id=project_id,
        run_id=run_id,
        expected_sequence=run.sequence,
        new_state="PLAN_ACCEPTED",
    )
    assert advanced.sequence == 2

    with pytest.raises(StateConflictError):
        state.transition_run(
            project_id=project_id,
            run_id=run_id,
            expected_sequence=run.sequence,
            new_state="RUNNING",
        )


def test_forbidden_run_transition_is_rejected(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    project_id = state.create_project(workspace_root=tmp_path / "workspace", project_id="PROJECT-A")
    run = state.create_run(project_id, run_id="RUN-A")

    with pytest.raises(InvalidTransitionError):
        state.transition_run(
            project_id=project_id,
            run_id=run.run_id,
            expected_sequence=run.sequence,
            new_state="COMPLETED",
        )


def test_event_hash_chain_detects_tampering(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    project_id = state.create_project(workspace_root=tmp_path / "workspace", project_id="PROJECT-A")
    run = state.create_run(project_id, run_id="RUN-A")
    state.transition_run(
        project_id=project_id,
        run_id=run.run_id,
        expected_sequence=run.sequence,
        new_state="PLAN_ACCEPTED",
    )

    state._connection.execute(
        "UPDATE execution_events SET payload_json=? WHERE project_id=? AND run_id=? AND sequence=?",
        ('{"state":"tampered"}', project_id, run.run_id, 2),
    )

    with pytest.raises(IntegrityError):
        state.verify_integrity(project_id=project_id, run_id=run.run_id)


def test_recovery_idempotency_key_prevents_duplicate_logical_operation(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    project_id, run_id, phase_id, attempt_id = seed_lineage(state, tmp_path)
    first, created_first = state.create_recovery_operation(
        project_id=project_id,
        run_id=run_id,
        phase_id=phase_id,
        task_id="TASK-A",
        attempt_id=attempt_id,
        operation_kind="LEASE_RECLAIM",
        idempotency_key="RUN-A:ATTEMPT-A:LEASE_RECLAIM",
    )
    second, created_second = state.create_recovery_operation(
        project_id=project_id,
        run_id=run_id,
        phase_id=phase_id,
        task_id="TASK-A",
        attempt_id=attempt_id,
        operation_kind="LEASE_RECLAIM",
        idempotency_key="RUN-A:ATTEMPT-A:LEASE_RECLAIM",
    )

    assert created_first is True
    assert created_second is False
    assert second == first


def test_cross_run_lineage_is_rejected(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    project_a = state.create_project(workspace_root=tmp_path / "a", project_id="PROJECT-A")
    project_b = state.create_project(workspace_root=tmp_path / "b", project_id="PROJECT-B")
    run_a = state.create_run(project_a, run_id="RUN-A")
    run_b = state.create_run(project_b, run_id="RUN-B")
    state.create_phase(project_id=project_a, run_id=run_a.run_id, phase_id="PHASE-A", ordinal=1, name="phase")
    state.create_phase(project_id=project_b, run_id=run_b.run_id, phase_id="PHASE-B", ordinal=1, name="phase")
    state.create_task(
        project_id=project_b,
        run_id=run_b.run_id,
        phase_id="PHASE-B",
        task_id="TASK-B",
    )

    with pytest.raises(LineageError):
        state.create_task(
            project_id=project_a,
            run_id=run_a.run_id,
            phase_id="PHASE-B",
            task_id="TASK-CROSS",
        )


def test_workspace_evidence_requires_same_attempt_lineage(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    project_id, run_id, phase_id, attempt_id = seed_lineage(state, tmp_path)
    evidence = WorkspaceEvidence(
        project_id=project_id,
        run_id=run_id,
        phase_id=phase_id,
        task_id="TASK-A",
        attempt_id=attempt_id,
        relative_path="target.txt",
        change_kind="MODIFIED",
        expected_before_identity="before",
        observed_before_identity="before",
        expected_after_identity="after",
        observed_after_identity="after",
        observed_state="PRESENT_COMPLETE",
        checkpoint_id=None,
        artifact_id=None,
        evidence_created_at=utc_now(),
    )
    assert state.record_workspace_evidence(evidence) > 0


def test_sqlite_foreign_keys_are_enabled(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    row = state._connection.execute("PRAGMA foreign_keys").fetchone()
    assert int(row[0]) == 1


def test_database_integrity_check(tmp_path: Path) -> None:
    state = make_state(tmp_path)
    result = state._connection.execute("PRAGMA integrity_check").fetchone()
    assert result[0] == "ok"
