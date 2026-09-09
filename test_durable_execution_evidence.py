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


def make_evidence(ids: dict[str, str], *, path: str = "target.txt", observed_state: str = "PRESENT_COMPLETE", checkpoint_id: str | None = None, artifact_id: str | None = None, before: str = "BEFORE", after: str = "AFTER") -> WorkspaceEvidence:
    return WorkspaceEvidence(
        project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"],
        relative_path=path, change_kind="MODIFIED", expected_before_identity=before, observed_before_identity=before,
        expected_after_identity=after, observed_after_identity=after, observed_state=observed_state,
        checkpoint_id=checkpoint_id, artifact_id=artifact_id, evidence_created_at="2026-09-09T12:00:00+00:00",
    )


def trust_checkpoint(state: DurableExecutionState, layer: EvidenceLayer, ids: dict[str, str], *, artifact_id: str | None = None, checkpoint_id: str = "CP-A") -> tuple[WorkspaceEvidence, object]:
    item = make_evidence(ids, artifact_id=artifact_id)
    layer.record_workspace_evidence(item)
    checkpoint = layer.create_checkpoint(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(item), checkpoint_id=checkpoint_id)
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
    assert reloaded._connection.execute("SELECT status FROM checkpoints WHERE checkpoint_id='CP-A'").fetchone()[0] == "TRUSTED"
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


@pytest.mark.parametrize("field,value", [
    ("expected_before_identity", "TAMPERED_BEFORE"),
    ("observed_before_identity", "TAMPERED_BEFORE"),
    ("expected_after_identity", "TAMPERED_AFTER"),
    ("observed_after_identity", "TAMPERED_AFTER"),
    ("observed_state", "MISMATCH"),
])
def test_workspace_evidence_identity_mutation_breaks_integrity(tmp_path: Path, field: str, value: str) -> None:
    state, layer, ids = seed(tmp_path)
    evidence_id = layer.record_workspace_evidence(make_evidence(ids))
    state._connection.execute(f"UPDATE workspace_evidence SET {field}=? WHERE evidence_id=?", (value, evidence_id))
    with pytest.raises(IntegrityError):
        layer.verify_integrity(project_id=ids["project"], run_id=ids["run"])


def test_workspace_evidence_checkpoint_and_artifact_correlation_mutation_breaks_integrity(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A")
    evidence_id = layer.record_workspace_evidence(make_evidence(ids))
    checkpoint = layer.create_checkpoint(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(make_evidence(ids)), checkpoint_id="CP-A")
    layer.transition_checkpoint(project_id=ids["project"], run_id=ids["run"], checkpoint_id=checkpoint.checkpoint_id, new_status="TRUSTED")
    state._connection.execute("UPDATE workspace_evidence SET checkpoint_id=? WHERE evidence_id=?", (checkpoint.checkpoint_id, evidence_id))
    with pytest.raises(IntegrityError):
        layer.verify_integrity(project_id=ids["project"], run_id=ids["run"])
    state._connection.execute("UPDATE workspace_evidence SET checkpoint_id=NULL, artifact_id=? WHERE evidence_id=?", (artifact.artifact_id, evidence_id))
    with pytest.raises(IntegrityError):
        layer.verify_integrity(project_id=ids["project"], run_id=ids["run"])


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


def test_artifact_validated_without_passed_validation_never_completes_task(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A")
    layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id=artifact.artifact_id, observed_identity="ID-A", observed_checksum=None)
    item, checkpoint = trust_checkpoint(state, layer, ids, artifact_id=artifact.artifact_id)
    validation = layer.create_validation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], checkpoint_sequence=checkpoint.sequence, validation_id="VAL-A", artifact_id=artifact.artifact_id)
    assert validation.state == "PENDING"
    assert layer.task_completion_ready(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], validation_id=validation.validation_id) is False
    with pytest.raises(IntegrityError, match="PASSED"):
        layer.complete_task(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], validation_id=validation.validation_id)
    state.close()


def test_validation_passed_wrong_artifact_rejected(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    artifact_a = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="a.bin", identity="ID-A")
    artifact_b = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-B", reference="b.bin", identity="ID-B")
    layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id=artifact_a.artifact_id, observed_identity="ID-A", observed_checksum=None)
    layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id=artifact_b.artifact_id, observed_identity="ID-B", observed_checksum=None)
    item, checkpoint = trust_checkpoint(state, layer, ids, artifact_id=artifact_a.artifact_id)
    validation = layer.create_validation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], checkpoint_sequence=checkpoint.sequence, validation_id="VAL-B", artifact_id=artifact_b.artifact_id)
    with pytest.raises(IntegrityError, match="artifact"):
        layer.transition_validation(project_id=ids["project"], run_id=ids["run"], validation_id=validation.validation_id, new_state="PASSED", evidence_hash=evidence_digest(item))


def test_validation_passed_wrong_checkpoint_rejected(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    first_item, first_checkpoint = trust_checkpoint(state, layer, ids, checkpoint_id="CP-A")
    second_item = make_evidence(ids, path="second.txt")
    layer.record_workspace_evidence(second_item)
    second_checkpoint = layer.create_checkpoint(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], sequence=2, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(second_item), checkpoint_id="CP-B")
    layer.transition_checkpoint(project_id=ids["project"], run_id=ids["run"], checkpoint_id=second_checkpoint.checkpoint_id, new_status="TRUSTED")
    validation = layer.create_validation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], checkpoint_sequence=second_checkpoint.sequence, validation_id="VAL-B")
    with pytest.raises(IntegrityError, match="evidence"):
        layer.transition_validation(project_id=ids["project"], run_id=ids["run"], validation_id=validation.validation_id, new_state="PASSED", evidence_hash=evidence_digest(first_item))
    assert first_checkpoint.status == "TRUSTED"


def test_artifact_invalidation_requires_revalidation(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A")
    layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id=artifact.artifact_id, observed_identity="ID-A", observed_checksum=None)
    item, checkpoint = trust_checkpoint(state, layer, ids, artifact_id=artifact.artifact_id)
    validation = layer.create_validation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], checkpoint_sequence=checkpoint.sequence, validation_id="VAL-A", artifact_id=artifact.artifact_id)
    layer.transition_validation(project_id=ids["project"], run_id=ids["run"], validation_id=validation.validation_id, new_state="PASSED", evidence_hash=evidence_digest(item))
    assert layer.transition_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id=artifact.artifact_id, new_state="ARTIFACT_INVALID").state == "ARTIFACT_INVALID"
    row = state._connection.execute("SELECT state FROM validations WHERE validation_id='VAL-A'").fetchone()
    assert row[0] == "REQUIRES_REVALIDATION"
    assert layer.task_completion_ready(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], validation_id="VAL-A") is False


def test_valid_artifact_alone_can_never_authorize_task_completion(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A")
    layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id=artifact.artifact_id, observed_identity="ID-A", observed_checksum=None)
    with pytest.raises(IntegrityError):
        layer.complete_task(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], validation_id="MISSING-VALIDATION")
    assert state._connection.execute("SELECT state FROM tasks WHERE task_id=?", (ids["task"],)).fetchone()[0] == "IN_PROGRESS"


def test_exact_passed_validation_is_the_task_completion_gate(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A")
    layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id=artifact.artifact_id, observed_identity="ID-A", observed_checksum=None)
    item, checkpoint = trust_checkpoint(state, layer, ids, artifact_id=artifact.artifact_id)
    validation = layer.create_validation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], checkpoint_sequence=checkpoint.sequence, validation_id="VAL-A", artifact_id=artifact.artifact_id)
    layer.transition_validation(project_id=ids["project"], run_id=ids["run"], validation_id=validation.validation_id, new_state="PASSED", evidence_hash=evidence_digest(item))
    assert layer.task_completion_ready(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], validation_id=validation.validation_id) is True
    layer.complete_task(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], validation_id=validation.validation_id)
    assert state._connection.execute("SELECT state FROM tasks WHERE task_id=?", (ids["task"],)).fetchone()[0] == "COMPLETED"


def test_validation_requires_revalidation_after_pass(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    item, checkpoint = trust_checkpoint(state, layer, ids)
    validation = layer.create_validation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], checkpoint_sequence=checkpoint.sequence, validation_id="VAL-A")
    layer.transition_validation(project_id=ids["project"], run_id=ids["run"], validation_id=validation.validation_id, new_state="PASSED", evidence_hash=evidence_digest(item))
    assert layer.transition_validation(project_id=ids["project"], run_id=ids["run"], validation_id=validation.validation_id, new_state="REQUIRES_REVALIDATION").state == "REQUIRES_REVALIDATION"
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
    assert layer.bind_lease(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], lease_id="LEASE-A", worker_id="W-A").state == "ACTIVE"
    with pytest.raises(StateConflictError):
        layer.bind_lease(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], lease_id="LEASE-B", worker_id="W-B")
    assert layer.transition_lease(project_id=ids["project"], run_id=ids["run"], lease_id="LEASE-A", new_state="STALE").state == "STALE"
    assert layer.transition_lease(project_id=ids["project"], run_id=ids["run"], lease_id="LEASE-A", new_state="RECLAIMED").state == "RECLAIMED"
    state.close()


def test_recovery_operation_idempotency_and_restart(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    first = layer.create_recovery_operation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], operation_kind="LEASE_RECLAIM", idempotency_key="RUN-A:ATTEMPT-A:LEASE_RECLAIM")
    second = layer.create_recovery_operation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], operation_kind="LEASE_RECLAIM", idempotency_key="RUN-A:ATTEMPT-A:LEASE_RECLAIM")
    assert first.operation_id == second.operation_id and first.operation_id != first.idempotency_key
    assert layer.transition_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_id=first.operation_id, new_state="STARTED").state == "STARTED"
    state.close()
    reloaded = DurableExecutionState(tmp_path / f"{ids['project']}.sqlite3")
    assert reloaded._connection.execute("SELECT state FROM recovery_operations WHERE operation_id=?", (first.operation_id,)).fetchone()[0] == "STARTED"
    reloaded.verify_integrity(project_id=ids["project"], run_id=ids["run"])


def test_unknown_recovery_operation_can_be_verified(tmp_path: Path) -> None:
    _, layer, ids = seed(tmp_path)
    op = layer.create_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_kind="EXTERNAL_EFFECT", idempotency_key="RUN-A:EXTERNAL_EFFECT")
    layer.transition_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_id=op.operation_id, new_state="STARTED")
    assert layer.transition_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_id=op.operation_id, new_state="UNKNOWN").state == "UNKNOWN"
    assert layer.transition_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_id=op.operation_id, new_state="VERIFIED", effect_reference="proof-ref", effect_hash="proof-hash").state == "VERIFIED"


def test_workspace_evidence_states_and_lineage_bindings(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    _, layer2, ids2 = seed(tmp_path, "PROJECT-B", "RUN-B")
    layer.record_workspace_evidence(make_evidence(ids, path="partial.txt", observed_state="PRESENT_PARTIAL"))
    layer.record_workspace_evidence(make_evidence(ids, path="mismatch.txt", observed_state="MISMATCH"))
    layer.record_workspace_evidence(make_evidence(ids, path="ambiguous.txt", observed_state="AMBIGUOUS"))
    _, checkpoint = trust_checkpoint(state, layer, ids)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A")
    assert layer.record_workspace_evidence(make_evidence(ids, path="bound.txt", checkpoint_id=checkpoint.checkpoint_id, artifact_id=artifact.artifact_id)) > 0
    with pytest.raises(LineageError):
        layer.record_workspace_evidence(make_evidence(ids2, checkpoint_id=checkpoint.checkpoint_id))
    layer2.state.close(); state.close()


def test_delivery_state_is_durable_but_not_verified_effect(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    assert layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_STARTED").delivery_state == "DELIVERY_STARTED"
    assert layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_INTERRUPTED").delivery_state == "DELIVERY_INTERRUPTED"
    assert layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_COMMITTED").delivery_state == "DELIVERY_COMMITTED"
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
    layer.verify_integrity(project_id=ids["project"], run_id=ids["run"])
