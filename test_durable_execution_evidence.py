from __future__ import annotations

from pathlib import Path

import pytest

from durable_execution_evidence import EvidenceLayer, evidence_digest
from durable_execution_state import (
    DurableExecutionState,
    IntegrityError,
    InvalidTransitionError,
    LineageError,
    StateConflictError,
    WorkspaceEvidence,
)


def seed(tmp_path: Path, project_id: str = "PROJECT-A", run_id: str = "RUN-A") -> tuple[DurableExecutionState, EvidenceLayer, dict[str, str]]:
    state = DurableExecutionState(tmp_path / f"{project_id}.sqlite3")
    workspace = tmp_path / project_id / "workspace"
    workspace.mkdir(parents=True)
    state.create_project(workspace_root=workspace, project_id=project_id)
    state.create_run(project_id, run_id=run_id)
    state.create_phase(project_id=project_id, run_id=run_id, phase_id=f"{run_id}-PHASE", ordinal=1, name="Phase")
    state.create_task(project_id=project_id, run_id=run_id, phase_id=f"{run_id}-PHASE", task_id=f"{run_id}-TASK", retry_class="IDEMPOTENT")
    attempt_id = f"{run_id}-ATTEMPT"
    state.create_attempt(project_id=project_id, run_id=run_id, phase_id=f"{run_id}-PHASE", task_id=f"{run_id}-TASK", attempt_id=attempt_id, worker_id="W1", lease_id=f"{run_id}-LEASE")
    ids = {"project": project_id, "run": run_id, "phase": f"{run_id}-PHASE", "task": f"{run_id}-TASK", "attempt": attempt_id}
    return state, EvidenceLayer(state), ids


def make_evidence(ids: dict[str, str], *, path: str = "target.txt", observed_state: str = "PRESENT_COMPLETE", checkpoint_id: str | None = None, artifact_id: str | None = None) -> WorkspaceEvidence:
    return WorkspaceEvidence(
        project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"],
        relative_path=path, change_kind="MODIFIED", expected_before_identity="BEFORE", observed_before_identity="BEFORE",
        expected_after_identity="AFTER", observed_after_identity="AFTER", observed_state=observed_state,
        checkpoint_id=checkpoint_id, artifact_id=artifact_id, evidence_created_at="2026-09-09T12:00:00+00:00",
    )


def trust_checkpoint(state: DurableExecutionState, layer: EvidenceLayer, ids: dict[str, str]) -> tuple[WorkspaceEvidence, object]:
    item = make_evidence(ids)
    layer.record_workspace_evidence(item)
    checkpoint = layer.create_checkpoint(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(item), checkpoint_id="CP-A")
    return item, layer.transition_checkpoint(project_id=ids["project"], run_id=ids["run"], checkpoint_id=checkpoint.checkpoint_id, new_status="TRUSTED")


def test_checkpoint_requires_real_matching_workspace_evidence(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    with pytest.raises(IntegrityError):
        layer.create_checkpoint(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash="BAD", checkpoint_id="CP-A")
    assert state.get_run(ids["run"], project_id=ids["project"]).sequence == 1


def test_checkpoint_lifecycle_and_reload(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    _, checkpoint = trust_checkpoint(state, layer, ids)
    assert checkpoint.status == "TRUSTED"
    state.close()
    reloaded = DurableExecutionState(tmp_path / f"{ids['project']}.sqlite3")
    row = reloaded._connection.execute("SELECT status FROM checkpoints WHERE checkpoint_id='CP-A'").fetchone()
    assert row[0] == "TRUSTED"
    reloaded.verify_integrity(project_id=ids["project"], run_id=ids["run"])


def test_cross_run_checkpoint_rejected(tmp_path: Path) -> None:
    state_a, layer_a, ids_a = seed(tmp_path, "PROJECT-A", "RUN-A")
    state_b, layer_b, ids_b = seed(tmp_path, "PROJECT-B", "RUN-B")
    item = make_evidence(ids_a)
    layer_a.record_workspace_evidence(item)
    with pytest.raises(LineageError):
        layer_b.create_checkpoint(project_id=ids_b["project"], run_id=ids_b["run"], phase_id=ids_a["phase"], task_id=ids_a["task"], attempt_id=ids_a["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(item), checkpoint_id="CP-CROSS")
    state_a.close(); state_b.close()


def test_checkpoint_sequence_mismatch_rejected(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    item = make_evidence(ids)
    layer.record_workspace_evidence(item)
    layer.create_checkpoint(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(item), checkpoint_id="CP-A")
    item2 = make_evidence(ids, path="second.txt")
    layer.record_workspace_evidence(item2)
    with pytest.raises(StateConflictError):
        layer.create_checkpoint(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(item2), checkpoint_id="CP-B")


def test_artifact_lifecycle_and_identity_checksum_checks(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="IDENTITY-A", checksum="CHECKSUM-A")
    assert artifact.state == "ARTIFACT_UNVALIDATED"
    with pytest.raises(IntegrityError, match="identity"):
        layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id="ART-A", observed_identity="WRONG", observed_checksum="CHECKSUM-A")
    with pytest.raises(IntegrityError, match="checksum"):
        layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id="ART-A", observed_identity="IDENTITY-A", observed_checksum="WRONG")
    assert layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id="ART-A", observed_identity="IDENTITY-A", observed_checksum="CHECKSUM-A").state == "ARTIFACT_VALIDATED"
    state.close()


def test_unvalidated_artifact_not_completion(tmp_path: Path) -> None:
    _, layer, ids = seed(tmp_path)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="IDENTITY-A")
    assert artifact.state != "ARTIFACT_VALIDATED"


def test_validation_requires_trusted_checkpoint_and_valid_artifact(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    item, checkpoint = trust_checkpoint(state, layer, ids)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A", checksum="HASH-A")
    validation = layer.create_validation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], checkpoint_sequence=checkpoint.sequence, validation_id="VAL-A", artifact_id=artifact.artifact_id)
    assert validation.state == "PENDING"
    with pytest.raises(IntegrityError):
        layer.transition_validation(project_id=ids["project"], run_id=ids["run"], validation_id="VAL-A", new_state="PASSED", evidence_hash="WRONG")
    layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id="ART-A", observed_identity="ID-A", observed_checksum="HASH-A")
    passed = layer.transition_validation(project_id=ids["project"], run_id=ids["run"], validation_id="VAL-A", new_state="PASSED", evidence_hash=evidence_digest(item))
    assert passed.state == "PASSED"
    state.close()


def test_validation_requires_revalidation_after_pass(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    item, checkpoint = trust_checkpoint(state, layer, ids)
    validation = layer.create_validation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], checkpoint_sequence=checkpoint.sequence, validation_id="VAL-A")
    layer.transition_validation(project_id=ids["project"], run_id=ids["run"], validation_id=validation.validation_id, new_state="PASSED", evidence_hash=evidence_digest(item))
    revalidate = layer.transition_validation(project_id=ids["project"], run_id=ids["run"], validation_id=validation.validation_id, new_state="REQUIRES_REVALIDATION")
    assert revalidate.state == "REQUIRES_REVALIDATION"
    state.close()


def test_cross_lineage_validation_rejected(tmp_path: Path) -> None:
    state_a, layer_a, ids_a = seed(tmp_path, "PROJECT-A", "RUN-A")
    state_b, layer_b, ids_b = seed(tmp_path, "PROJECT-B", "RUN-B")
    _, checkpoint = trust_checkpoint(state_a, layer_a, ids_a)
    with pytest.raises(LineageError):
        layer_b.create_validation(project_id=ids_b["project"], run_id=ids_b["run"], phase_id=ids_a["phase"], task_id=ids_a["task"], attempt_id=ids_a["attempt"], checkpoint_sequence=checkpoint.sequence, validation_id="VAL-CROSS")
    state_a.close(); state_b.close()


def test_lease_binding_lifecycle_and_duplicate_active_ownership(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    active = layer.bind_lease(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], lease_id="LEASE-A", worker_id="W-A")
    assert active.state == "ACTIVE"
    with pytest.raises(StateConflictError):
        layer.bind_lease(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], lease_id="LEASE-B", worker_id="W-B")
    assert layer.transition_lease(project_id=ids["project"], run_id=ids["run"], lease_id="LEASE-A", new_state="STALE").state == "STALE"
    assert layer.transition_lease(project_id=ids["project"], run_id=ids["run"], lease_id="LEASE-A", new_state="RECLAIMED").state == "RECLAIMED"
    state.close()


def test_recovery_operation_idempotency_and_restart(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    first = layer.create_recovery_operation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], operation_kind="LEASE_RECLAIM", idempotency_key="RUN-A:ATTEMPT-A:LEASE_RECLAIM")
    second = layer.create_recovery_operation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], operation_kind="LEASE_RECLAIM", idempotency_key="RUN-A:ATTEMPT-A:LEASE_RECLAIM")
    assert first.operation_id == second.operation_id
    assert first.operation_id != first.idempotency_key
    assert layer.transition_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_id=first.operation_id, new_state="STARTED").state == "STARTED"
    state.close()
    reloaded = DurableExecutionState(tmp_path / f"{ids['project']}.sqlite3")
    row = reloaded._connection.execute("SELECT state FROM recovery_operations WHERE operation_id=?", (first.operation_id,)).fetchone()
    assert row[0] == "STARTED"
    reloaded.verify_integrity(project_id=ids["project"], run_id=ids["run"])


def test_unknown_recovery_operation_can_be_verified(tmp_path: Path) -> None:
    _, layer, ids = seed(tmp_path)
    op = layer.create_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_kind="EXTERNAL_EFFECT", idempotency_key="RUN-A:EXTERNAL_EFFECT")
    layer.transition_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_id=op.operation_id, new_state="STARTED")
    unknown = layer.transition_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_id=op.operation_id, new_state="UNKNOWN")
    assert unknown.state == "UNKNOWN"
    verified = layer.transition_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_id=op.operation_id, new_state="VERIFIED", effect_reference="proof-ref", effect_hash="proof-hash")
    assert verified.state == "VERIFIED"


def test_workspace_evidence_states_and_lineage_bindings(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    checkpoint_state, layer2, ids2 = seed(tmp_path, "PROJECT-B", "RUN-B")
    del checkpoint_state, layer2
    layer.record_workspace_evidence(make_evidence(ids, path="partial.txt", observed_state="PRESENT_PARTIAL"))
    layer.record_workspace_evidence(make_evidence(ids, path="mismatch.txt", observed_state="MISMATCH"))
    layer.record_workspace_evidence(make_evidence(ids, path="ambiguous.txt", observed_state="AMBIGUOUS"))
    checkpoint_item, checkpoint = trust_checkpoint(state, layer, ids)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A")
    bound = make_evidence(ids, path="bound.txt", checkpoint_id=checkpoint.checkpoint_id, artifact_id=artifact.artifact_id)
    assert layer.record_workspace_evidence(bound) > 0
    with pytest.raises(LineageError):
        layer.record_workspace_evidence(make_evidence(ids2, checkpoint_id=checkpoint.checkpoint_id))
    assert checkpoint_item.attempt_id == ids["attempt"]
    state.close()


def test_delivery_state_is_durable_but_not_verified_effect(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    assert layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_STARTED").delivery_state == "DELIVERY_STARTED"
    assert layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_INTERRUPTED").delivery_state == "DELIVERY_INTERRUPTED"
    committed = layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_COMMITTED")
    assert committed.delivery_state == "DELIVERY_COMMITTED"
    state.close()
    reloaded = DurableExecutionState(tmp_path / f"{ids['project']}.sqlite3")
    assert reloaded.get_run(ids["run"], project_id=ids["project"]).delivery_state == "DELIVERY_COMMITTED"


def test_failed_transition_rolls_back_event_and_snapshot(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    before = state.get_run(ids["run"], project_id=ids["project"])
    with pytest.raises(InvalidTransitionError):
        layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_VERIFIED")
    after = state.get_run(ids["run"], project_id=ids["project"])
    assert (after.sequence, after.delivery_state) == (before.sequence, before.delivery_state)
    state.verify_integrity(project_id=ids["project"], run_id=ids["run"])
