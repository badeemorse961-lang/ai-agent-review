from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from durable_execution_evidence import EvidenceLayer, evidence_digest
from durable_execution_state import DurableExecutionState, WorkspaceEvidence, StateConflictError
from test_orchestration_durable import build_durable_orchestrator
from workspace_delivery_recovery import WorkspaceDeliveryRecovery


def _project_id(root: Path) -> str:
    return "PROJECT-" + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:24]


def _fixture(tmp_path: Path, *, artifact_state: str = "ARTIFACT_VALIDATED", delivery_state: str = "DELIVERY_PENDING"):
    root = tmp_path / "project"; root.mkdir()
    orchestrator, state, _, _ = build_durable_orchestrator(root, tmp_path / "execution.sqlite3")
    bridge = orchestrator._durable
    run_id = bridge.create_run(); bridge.accept_plan(run_id, "GOAL", {"tasks": [{"task_id": "TASK-1"}]})
    phase_id = run_id + ":PHASE:1"; bridge.start_phase(run_id, phase_id); bridge.start_running(run_id)
    task_id = "TASK-1"; bridge.start_task(run_id, phase_id, {"task_id": task_id, "objective": "workspace recovery", "retry_class": "IDEMPOTENT", "depends_on": []})
    attempt_id = run_id + ":TASK-1:ATTEMPT:1"; bridge.start_attempt(run_id, phase_id, task_id, attempt_id, "W-1")
    path = root / "artifact.txt"; path.write_text("v1", encoding="utf-8")
    identity = "sha256:" + hashlib.sha256(b"v1").hexdigest(); checksum = identity.removeprefix("sha256:")
    EvidenceLayer(state).register_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1", reference="artifact.txt", identity=identity, checksum=checksum)
    evidence = WorkspaceEvidence(bridge.project_id, run_id, phase_id, task_id, attempt_id, "artifact.txt", "CREATED", None, None, identity, identity, "PRESENT_COMPLETE", None, "ART-1", "2026-09-09T00:00:00+00:00")
    EvidenceLayer(state).record_workspace_evidence(evidence)
    checkpoint = EvidenceLayer(state).create_checkpoint(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, sequence=1, checkpoint_kind="WORKSPACE", workspace_evidence_identity=identity, workspace_evidence_hash=evidence_digest(evidence), checkpoint_id="CP-1")
    EvidenceLayer(state).transition_checkpoint(project_id=bridge.project_id, run_id=run_id, checkpoint_id=checkpoint.checkpoint_id, new_status="TRUSTED")
    if artifact_state == "ARTIFACT_VALIDATED":
        EvidenceLayer(state).validate_artifact(project_id=bridge.project_id, run_id=run_id, artifact_id="ART-1", observed_identity=identity, observed_checksum=checksum)
    validation = EvidenceLayer(state).create_validation(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, checkpoint_sequence=1, validation_id="VAL-1", artifact_id="ART-1")
    if artifact_state == "ARTIFACT_VALIDATED":
        EvidenceLayer(state).transition_validation(project_id=bridge.project_id, run_id=run_id, validation_id=validation.validation_id, new_state="PASSED", evidence_hash=evidence_digest(evidence))
    evidence_layer = EvidenceLayer(state)
    if delivery_state != "DELIVERY_PENDING":
        evidence_layer.set_delivery_state(project_id=bridge.project_id, run_id=run_id, new_state="DELIVERY_STARTED")
        if delivery_state != "DELIVERY_STARTED":
            evidence_layer.set_delivery_state(project_id=bridge.project_id, run_id=run_id, new_state=delivery_state)
    return root, state, bridge, run_id, phase_id, task_id, attempt_id, path, identity


def test_exact_match_preserves_validated_artifact(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, path, _ = _fixture(tmp_path)
    decision = WorkspaceDeliveryRecovery(state, root).inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    assert decision.classification == "COMPLETE" and decision.action == "PRESERVE"
    assert state._connection.execute("SELECT state FROM artifacts WHERE artifact_id='ART-1'").fetchone()[0] == "ARTIFACT_VALIDATED"
    assert path.read_text(encoding="utf-8") == "v1"


def test_validated_artifact_modified_after_validation_requires_revalidation(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, path, _ = _fixture(tmp_path)
    path.write_text("v2", encoding="utf-8")
    decision = WorkspaceDeliveryRecovery(state, root).inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    assert decision.classification == "MISMATCH"
    assert state._connection.execute("SELECT state FROM artifacts WHERE artifact_id='ART-1'").fetchone()[0] == "ARTIFACT_INVALID"
    assert state._connection.execute("SELECT state FROM validations WHERE validation_id='VAL-1'").fetchone()[0] == "REQUIRES_REVALIDATION"


def test_unvalidated_existing_file_is_not_validation(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, *_ = _fixture(tmp_path, artifact_state="ARTIFACT_UNVALIDATED")
    decision = WorkspaceDeliveryRecovery(state, root).inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    assert decision.classification == "PARTIAL"
    assert state._connection.execute("SELECT state FROM artifacts WHERE artifact_id='ART-1'").fetchone()[0] == "ARTIFACT_UNVALIDATED"


def test_absent_artifact_is_not_completed(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, path, _ = _fixture(tmp_path)
    path.unlink()
    decision = WorkspaceDeliveryRecovery(state, root).inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    assert decision.classification == "ABSENT"
    assert state._connection.execute("SELECT state FROM validations WHERE validation_id='VAL-1'").fetchone()[0] == "REQUIRES_REVALIDATION"


def test_checkpoint_trust_does_not_survive_workspace_mutation(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, path, _ = _fixture(tmp_path)
    path.write_text("changed", encoding="utf-8")
    decision = WorkspaceDeliveryRecovery(state, root).inspect_checkpoint(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, checkpoint_id="CP-1")
    assert decision.classification == "MISMATCH"
    assert state._connection.execute("SELECT status FROM checkpoints WHERE checkpoint_id='CP-1'").fetchone()[0] == "INVALID"
    assert state._connection.execute("SELECT state FROM validations WHERE validation_id='VAL-1'").fetchone()[0] == "REQUIRES_REVALIDATION"


def test_partial_workspace_is_durable(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, path, _ = _fixture(tmp_path, artifact_state="ARTIFACT_UNVALIDATED")
    path.write_bytes(b"")
    decision = WorkspaceDeliveryRecovery(state, root).inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    row = state._connection.execute("SELECT observed_state FROM workspace_evidence WHERE evidence_id=?", (decision.evidence_id,)).fetchone()
    assert decision.classification == "MISMATCH" and row[0] == "MISMATCH"


def test_ambiguous_non_file_reference_never_completes(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, *_ = _fixture(tmp_path)
    ambiguous_root = root / "ambiguous"; ambiguous_root.mkdir()
    state._connection.execute("UPDATE artifacts SET reference='ambiguous' WHERE artifact_id='ART-1'")
    decision = WorkspaceDeliveryRecovery(state, root).inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    assert decision.classification == "AMBIGUOUS"


def test_no_destructive_cleanup(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, path, _ = _fixture(tmp_path)
    WorkspaceDeliveryRecovery(state, root).inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    assert path.exists()


def test_delivery_recovery_transitions_started_to_recovery_required(tmp_path: Path):
    root, state, bridge, run_id, *_ = _fixture(tmp_path, delivery_state="DELIVERY_STARTED")
    decision = WorkspaceDeliveryRecovery(state, root).recover_delivery(project_id=bridge.project_id, run_id=run_id)
    assert decision.state_after == "DELIVERY_RECOVERY_REQUIRED"


def test_delivery_committed_is_not_verified_automatically(tmp_path: Path):
    root, state, bridge, run_id, *_ = _fixture(tmp_path, delivery_state="DELIVERY_COMMITTED")
    decision = WorkspaceDeliveryRecovery(state, root).recover_delivery(project_id=bridge.project_id, run_id=run_id)
    assert decision.state_after == "DELIVERY_COMMITTED"


def test_delivery_ambiguity_is_durable_and_not_replayed(tmp_path: Path):
    root, state, bridge, run_id, *_ = _fixture(tmp_path, delivery_state="DELIVERY_INTERRUPTED")
    recovery = WorkspaceDeliveryRecovery(state, root)
    first = recovery.recover_delivery(project_id=bridge.project_id, run_id=run_id, effect_state="UNKNOWN")
    count = state._connection.execute("SELECT COUNT(*) FROM recovery_operations WHERE project_id=? AND run_id=? AND operation_kind='M6_DELIVERY_RECOVERY'", (bridge.project_id, run_id)).fetchone()[0]
    events = len(state.get_events(project_id=bridge.project_id, run_id=run_id))
    second = recovery.recover_delivery(project_id=bridge.project_id, run_id=run_id, effect_state="UNKNOWN")
    assert first.recovery_operation_id == second.recovery_operation_id
    assert count == state._connection.execute("SELECT COUNT(*) FROM recovery_operations WHERE project_id=? AND run_id=? AND operation_kind='M6_DELIVERY_RECOVERY'", (bridge.project_id, run_id)).fetchone()[0]
    assert events == len(state.get_events(project_id=bridge.project_id, run_id=run_id))


def test_workspace_recovery_operation_is_idempotent(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, *_ = _fixture(tmp_path)
    recovery = WorkspaceDeliveryRecovery(state, root)
    first = recovery.inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    events = len(state.get_events(project_id=bridge.project_id, run_id=run_id))
    second = recovery.inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    assert first.recovery_operation_id == second.recovery_operation_id
    assert events == len(state.get_events(project_id=bridge.project_id, run_id=run_id))


def test_sequence_fence_rejects_stale_workspace_observation(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, *_ = _fixture(tmp_path)
    current = state.get_run(run_id, project_id=bridge.project_id)
    with pytest.raises(StateConflictError):
        WorkspaceDeliveryRecovery(state, root).inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1", expected_sequence=current.sequence - 1)


def test_cross_project_run_isolation(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, *_ = _fixture(tmp_path)
    other_root = tmp_path / "other"; other_root.mkdir(); other_project = _project_id(other_root)
    state.create_project(workspace_root=other_root, project_id=other_project); other_run = state.create_run(other_project)
    with pytest.raises(Exception):
        WorkspaceDeliveryRecovery(state, root).inspect_artifact(project_id=other_project, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    assert state.get_run(other_run.run_id, project_id=other_project).state == "CREATED"


def test_completion_gate_remains_closed_after_mismatch(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, path, _ = _fixture(tmp_path)
    path.write_text("v3", encoding="utf-8")
    WorkspaceDeliveryRecovery(state, root).inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    assert EvidenceLayer(state).task_completion_ready(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, validation_id="VAL-1") is False


def test_close_reopen_preserves_workspace_recovery_evidence(tmp_path: Path):
    root, state, bridge, run_id, phase_id, task_id, attempt_id, path, _ = _fixture(tmp_path)
    path.write_text("v2", encoding="utf-8")
    WorkspaceDeliveryRecovery(state, root).inspect_artifact(project_id=bridge.project_id, run_id=run_id, phase_id=phase_id, task_id=task_id, attempt_id=attempt_id, artifact_id="ART-1")
    db = state.database_path; project_id = bridge.project_id; state.close()
    reopened = DurableExecutionState(db)
    row = reopened._connection.execute("SELECT observed_state FROM workspace_evidence WHERE project_id=? AND run_id=? ORDER BY evidence_id DESC LIMIT 1", (project_id, run_id)).fetchone()
    assert row[0] == "MISMATCH"
