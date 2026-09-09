from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from central_leader import CentralLeader
from durable_execution_state import DurableExecutionState, StateConflictError
from execution_authorization import ExecutionAuthorizationBoundary
from orchestration import CanonicalOrchestrator, WorkerExecutionSpec, default_validator_factory
from plan_decomposer import PlanDecomposer
from worker_dispatch import WorkerDispatcher
from worker_execution import WorkerExecutionBoundary
from test_orchestration import StubLeaderRouter, StubWorkerAdapter, StubWorkerRouter, StubUnderstanding, StubAuthorization


def build_durable_orchestrator(root: Path, db: Path, *, worker_adapter: StubWorkerAdapter | None = None):
    leader_router = StubLeaderRouter()
    worker_router = StubWorkerRouter(worker_ids=("W-1",))
    understanding = StubUnderstanding({
        "authority": {"execution_authorized": False, "mutation_allowed": False, "source_contents_included": False},
        "project": {"state": "BUILD", "autonomous_start_allowed": True},
    })
    worker_adapter = worker_adapter or StubWorkerAdapter(changes=False)
    state = DurableExecutionState(db)

    def executor(request: Any) -> tuple[int, str, str, bool]:
        del request
        return 0, "worker ok", "", False

    worker_execution = WorkerExecutionBoundary(
        root,
        executor=executor,
        checkpoint=lambda request: {"isolated": True, "checkpoint_id": request.task_id + ":cp"},
        active_lease_lookup=lambda task_id: worker_router.active_leases().get(task_id),
    )
    leader = CentralLeader(
        router=leader_router,
        transport=lambda request: {"plan": {"goal": "durable task", "tasks": [{
            "task_id": request.task_id + ":1",
            "role": "coder",
            "objective": "record durable lifecycle",
            "depends_on": [],
            "acceptance_criteria": ["tests pass"],
        }]}},
    )
    orchestrator = CanonicalOrchestrator(
        root,
        understanding=understanding,
        leader=leader,
        decomposer=PlanDecomposer(allowed_roles=["coder"]),
        dispatcher=WorkerDispatcher(router=worker_router),
        worker_execution=worker_execution,
        worker_adapter=worker_adapter,
        validator_factory=default_validator_factory(root),
        authorization=StubAuthorization(),
        durable_state=state,
    )
    return orchestrator, state, leader_router, worker_router


def test_real_orchestration_persists_complete_durable_lifecycle(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    orchestrator, state, _, _ = build_durable_orchestrator(root, tmp_path / "execution.sqlite3")

    result = orchestrator.run("GOAL-1")
    assert result.status == "APPROVED"
    assert result.durable_project_id is not None
    assert result.durable_run_id is not None
    assert result.durable_phase_id is not None

    run_id = result.durable_run_id
    project_id = result.durable_project_id
    phase_id = result.durable_phase_id
    task_id = result.task_records[0].task["task_id"]
    rows = state._connection.execute("SELECT state FROM phases WHERE project_id=? AND run_id=? AND phase_id=?", (project_id, run_id, phase_id)).fetchall()
    assert rows[0][0] == "COMPLETED"
    task_row = state._connection.execute("SELECT state, latest_attempt_id FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (project_id, run_id, phase_id, task_id)).fetchone()
    assert task_row[0] == "COMPLETED"
    attempt_id = task_row[1]
    attempt_row = state._connection.execute("SELECT state, validation_id, checkpoint_sequence FROM attempts WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (project_id, run_id, phase_id, task_id, attempt_id)).fetchone()
    assert attempt_row[0] == "VALIDATED"
    assert attempt_row[1]
    assert attempt_row[2] == 1
    checkpoint = state._connection.execute("SELECT status FROM checkpoints WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (project_id, run_id, phase_id, task_id, attempt_id)).fetchone()
    assert checkpoint[0] == "TRUSTED"
    artifact = state._connection.execute("SELECT state FROM artifacts WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (project_id, run_id, phase_id, task_id, attempt_id)).fetchone()
    assert artifact[0] == "ARTIFACT_VALIDATED"
    validation = state._connection.execute("SELECT state, checkpoint_sequence FROM validations WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=?", (project_id, run_id, phase_id, task_id, attempt_id)).fetchone()
    assert validation[0] == "PASSED"
    assert validation[1] == 1
    run = state.get_run(run_id, project_id=project_id)
    assert run.state == "COMPLETED"
    event_types = [row["event_type"] for row in state.get_events(project_id=project_id, run_id=run_id)]
    assert {"RUN_CREATED", "PLAN_ACCEPTED", "PHASE_CREATED", "PHASE_STARTED", "RUN_STARTED", "TASK_CREATED", "TASK_STARTED", "ATTEMPT_STARTED", "ARTIFACT_REGISTERED", "WORKSPACE_EVIDENCE_RECORDED", "CHECKPOINT_CREATED", "CHECKPOINT_TRUSTED", "ARTIFACT_VALIDATED", "VALIDATION_CREATED", "VALIDATION_PASSED", "TASK_COMPLETED", "PHASE_COMPLETED", "RUN_COMPLETED"}.issubset(set(event_types))
    assert len(event_types) == run.sequence
    state.verify_integrity(project_id=project_id, run_id=run_id)
    state.close()


def test_durable_state_survives_orchestrator_object_discard(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    db = tmp_path / "execution.sqlite3"
    orchestrator, state, _, _ = build_durable_orchestrator(root, db)
    result = orchestrator.run("GOAL-RELOAD")
    project_id, run_id = result.durable_project_id, result.durable_run_id
    state.close()
    reopened = DurableExecutionState(db)
    run = reopened.get_run(run_id, project_id=project_id)
    assert run.state == "COMPLETED"
    assert reopened.get_events(project_id=project_id, run_id=run_id)[-1]["event_type"] == "RUN_COMPLETED"
    reopened.verify_integrity(project_id=project_id, run_id=run_id)


def test_sequence_fence_rejects_stale_run_transition(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    _, state, _, _ = build_durable_orchestrator(root, tmp_path / "execution.sqlite3")
    project_id = "PROJECT-" + __import__("hashlib").sha256(str(root.resolve()).encode()).hexdigest()[:24]
    run = state.create_run(project_id)
    current = state.get_run(run.run_id, project_id=project_id)
    state.transition_run(project_id=project_id, run_id=run.run_id, expected_sequence=current.sequence, new_state="PLAN_ACCEPTED")
    with pytest.raises(StateConflictError):
        state.transition_run(project_id=project_id, run_id=run.run_id, expected_sequence=current.sequence, new_state="RUNNING")


def test_duplicate_child_transition_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    orchestrator, state, _, _ = build_durable_orchestrator(root, tmp_path / "execution.sqlite3")
    bridge = orchestrator._durable
    run_id = bridge.create_run()
    bridge.accept_plan(run_id, "GOAL", {"tasks": []})
    phase_id = run_id + ":PHASE:1"
    bridge.start_phase(run_id, phase_id)
    before = len(state.get_events(project_id=bridge.project_id, run_id=run_id))
    bridge.start_phase(run_id, phase_id)
    after = len(state.get_events(project_id=bridge.project_id, run_id=run_id))
    assert before == after


def test_project_and_run_isolation(tmp_path: Path) -> None:
    root_a = tmp_path / "project-a"; root_a.mkdir()
    root_b = tmp_path / "project-b"; root_b.mkdir()
    db = tmp_path / "shared.sqlite3"
    orch_a, state, _, _ = build_durable_orchestrator(root_a, db)
    orch_b, _, _, _ = build_durable_orchestrator(root_b, db)
    result_a = orch_a.run("GOAL-A")
    result_b = orch_b.run("GOAL-B")
    assert result_a.durable_project_id != result_b.durable_project_id
    assert result_a.durable_run_id != result_b.durable_run_id
    assert len(state.get_events(project_id=result_a.durable_project_id, run_id=result_a.durable_run_id)) > 1
    assert len(state.get_events(project_id=result_b.durable_project_id, run_id=result_b.durable_run_id)) > 1
    with pytest.raises(Exception):
        state.get_run(result_a.durable_run_id, project_id=result_b.durable_project_id)


def test_completion_is_gated_by_m2_validation_authority(tmp_path: Path) -> None:
    root = tmp_path / "project"; root.mkdir()
    adapter = StubWorkerAdapter(changes=False)
    orchestrator, state, _, _ = build_durable_orchestrator(root, tmp_path / "execution.sqlite3", worker_adapter=adapter)
    result = orchestrator.run("GOAL-GATED")
    project_id, run_id, phase_id = result.durable_project_id, result.durable_run_id, result.durable_phase_id
    task_id = result.plan["tasks"][0]["task_id"]
    validation = state._connection.execute("SELECT validation_id, state FROM validations WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (project_id, run_id, phase_id, task_id)).fetchone()
    assert validation[1] == "PASSED"
    task = state._connection.execute("SELECT state FROM tasks WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=?", (project_id, run_id, phase_id, task_id)).fetchone()
    assert task[0] == "COMPLETED"
    assert validation[0].endswith(":VALIDATION:1")
    state.close()
