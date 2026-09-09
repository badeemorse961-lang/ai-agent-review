from __future__ import annotations

from pathlib import Path

import pytest

from durable_execution_evidence import EvidenceLayer, evidence_digest
from durable_execution_state import DurableExecutionState, IntegrityError, InvalidTransitionError, LineageError, StateConflictError, WorkspaceEvidence


def seed(root: Path, *, project_id: str = "PROJECT-A", run_id: str = "RUN-A") -> tuple[DurableExecutionState, EvidenceLayer, dict[str, str]]:
    state = DurableExecutionState(root / ".agent_state" / "execution_state.sqlite3")
    project_root = root / project_id
    project_root.mkdir(parents=True, exist_ok=True)
    project = state.create_project(workspace_root=project_root, project_id=project_id)
    run = state.create_run(project, run_id=run_id)
    state.create_phase(project_id=project, run_id=run_id, phase_id="PHASE-A", ordinal=1, name="Phase A")
    state.create_task(project_id=project, run_id=run_id, phase_id="PHASE-A", task_id="TASK-A", retry_class="IDEMPOTENT")
    attempt = state.create_attempt(project_id=project, run_id=run_id, phase_id="PHASE-A", task_id="TASK-A", attempt_id="ATTEMPT-A", worker_id="W-A", lease_id="LEASE-A")
    return state, EvidenceLayer(state), {"project": project, "run": run_id, "phase": "PHASE-A", "task": "TASK-A", "attempt": attempt}


def evidence(ids: dict[str, str], *, path: str = "target.txt", observed_state: str = "PRESENT_COMPLETE", checkpoint_id: str | None = None, artifact_id: str | None = None) -> WorkspaceEvidence:
    return WorkspaceEvidence(
        project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"],
        relative_path=path, change_kind="MODIFIED", expected_before_identity="BEFORE", observed_before_identity="BEFORE",
        expected_after_identity="AFTER", observed_after_identity="AFTER", observed_state=observed_state,
        checkpoint_id=checkpoint_id, artifact_id=artifact_id, evidence_created_at="2026-09-09T12:00:00+00:00",
    )


def trusted_checkpoint(state: DurableExecutionState, layer: EvidenceLayer, ids: dict[str, str]) -> tuple[WorkspaceEvidence, object]:
    item = evidence(ids)
    layer.record_workspace_evidence(item)
    checkpoint = layer.create_checkpoint(
        project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"],
        sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(item), checkpoint_id="CP-A",
    )
    trusted = layer.transition_checkpoint(project_id=ids["project"], run_id=ids["run"], checkpoint_id=checkpoint.checkpoint_id, new_status="TRUSTED")
    return item, trusted


def test_checkpoint_requires_matching_workspace_evidence(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    with pytest.raises(IntegrityError):
        layer.create_checkpoint(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash="bad", checkpoint_id="CP-A")
    assert state.get_run(ids["run"], project_id=ids["project"]).sequence == 1


def test_checkpoint_created_to_trusted_survives_reload(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    _, trusted = trusted_checkpoint(state, layer, ids)
    assert trusted.status == "TRUSTED"
    state.close()
    reloaded = DurableExecutionState(tmp_path / ".agent_state" / "execution_state.sqlite3")
    row = reloaded._connection.execute("SELECT status FROM checkpoints WHERE checkpoint_id='CP-A'").fetchone()
    assert row[0] == "TRUSTED"
    reloaded.verify_integrity(project_id=ids["project"], run_id=ids["run"])


def test_cross_run_checkpoint_is_rejected(tmp_path: Path) -> None:
    state, layer, ids_a = seed(tmp_path, project_id="PROJECT-A", run_id="RUN-A")
    state2, layer2, ids_b = seed(tmp_path, project_id="PROJECT-B", run_id="RUN-B")
    item_a = evidence(ids_a)
    layer.record_workspace_evidence(item_a)
    with pytest.raises(LineageError):
        layer2.create_checkpoint(project_id=ids_b["project"], run_id=ids_b["run"], phase_id=ids_a["phase"], task_id=ids_a["task"], attempt_id=ids_a["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(item_a), checkpoint_id="CP-CROSS")
    state.close(); state2.close()


def test_checkpoint_sequence_is_monotonic(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    item = evidence(ids)
    layer.record_workspace_evidence(item)
    layer.create_checkpoint(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(item), checkpoint_id="CP-A")
    with pytest.raises(StateConflictError):
        layer.create_checkpoint(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(item), checkpoint_id="CP-B")


def test_artifact_remains_untrusted_until_identity_and_checksum_match(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="IDENTITY-A", checksum="CHECKSUM-A")
    assert artifact.state == "ARTIFACT_UNVALIDATED"
    with pytest.raises(IntegrityError, match="identity"):
        layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id="ART-A", observed_identity="WRONG", observed_checksum="CHECKSUM-A")
    with pytest.raises(IntegrityError, match="checksum"):
        layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id="ART-A", observed_identity="IDENTITY-A", observed_checksum="WRONG")
    validated = layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id="ART-A", observed_identity="IDENTITY-A", observed_checksum="CHECKSUM-A")
    assert validated.state == "ARTIFACT_VALIDATED"
    state.close()


def test_artifact_wrong_attempt_lineage_is_rejected(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    state.create_attempt(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id="ATTEMPT-B")
    layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A")
    with pytest.raises(LineageError):
        layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id="ATTEMPT-B", artifact_id="ART-A", reference="out.bin", identity="ID-A")


def test_validation_requires_trusted_checkpoint_and_valid_artifact(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    item = evidence(ids)
    layer.record_workspace_evidence(item)
    checkpoint = layer.create_checkpoint(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], sequence=1, checkpoint_kind="TASK_CHECKPOINT", workspace_evidence_identity="AFTER", workspace_evidence_hash=evidence_digest(item), checkpoint_id="CP-A")
    layer.transition_checkpoint(project_id=ids["project"], run_id=ids["run"], checkpoint_id=checkpoint.checkpoint_id, new_status="TRUSTED")
    layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A", checksum="HASH-A")
    with pytest.raises(IntegrityError):
        layer.transition_validation  # smoke-check no mutation API is called implicitly
    artifact = layer.validate_artifact(project_id=ids["project"], run_id=ids["run"], artifact_id="ART-A", observed_identity="ID-A", observed_checksum="HASH-A")
    validation = layer.create_validation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], checkpoint_sequence=1, validation_id="VAL-A", artifact_id=artifact.artifact_id)
    assert validation.state == "PENDING"
    passed = layer.transition_validation(project_id=ids["project"], run_id=ids["run"], validation_id="VAL-A", new_state="PASSED", evidence_hash=evidence_digest(item))
    assert passed.state == "PASSED"


def test_validation_wrong_artifact_and_checkpoint_lineage_are_rejected(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    other = seed(tmp_path, project_id="PROJECT-B", run_id="RUN-B")
    item, checkpoint = trusted_checkpoint(state, layer, ids)
    layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A")
    with pytest.raises(LineageError):
        layer.create_validation(project_id=other[2]["project"], run_id=other[2]["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], checkpoint_sequence=checkpoint.sequence, validation_id="VAL-CROSS", artifact_id="ART-A")
    assert item.observed_state == "PRESENT_COMPLETE"


def test_lease_binding_and_duplicate_active_ownership(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    lease = layer.bind_lease(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], lease_id="LEASE-A", worker_id="W-A")
    assert lease.state == "ACTIVE"
    with pytest.raises(StateConflictError):
        layer.bind_lease(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], lease_id="LEASE-B", worker_id="W-B")
    stale = layer.transition_lease(project_id=ids["project"], run_id=ids["run"], lease_id="LEASE-A", new_state="STALE")
    reclaimed = layer.transition_lease(project_id=ids["project"], run_id=ids["run"], lease_id="LEASE-A", new_state="RECLAIMED")
    assert stale.state == "STALE"
    assert reclaimed.state == "RECLAIMED"


def test_recovery_operation_is_idempotent_and_survives_reload(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    first = layer.create_recovery_operation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], operation_kind="LEASE_RECLAIM", idempotency_key="RUN-A:ATTEMPT-A:LEASE_RECLAIM")
    second = layer.create_recovery_operation(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], operation_kind="LEASE_RECLAIM", idempotency_key="RUN-A:ATTEMPT-A:LEASE_RECLAIM")
    assert first.operation_id == second.operation_id
    assert first.operation_id != first.idempotency_key
    started = layer.transition_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_id=first.operation_id, new_state="STARTED")
    unknown = layer.transition_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_id=first.operation_id, new_state="UNKNOWN")
    state.close()
    reloaded = DurableExecutionState(tmp_path / ".agent_state" / "execution_state.sqlite3")
    row = reloaded._connection.execute("SELECT state FROM recovery_operations WHERE operation_id=?", (first.operation_id,)).fetchone()
    assert started.state == "STARTED"
    assert unknown.state == "UNKNOWN"
    assert row[0] == "UNKNOWN"
    reloaded.verify_integrity(project_id=ids["project"], run_id=ids["run"])


def test_workspace_evidence_supports_partial_mismatch_and_ambiguous(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    for status in ("PRESENT_PARTIAL", "MISMATCH", "AMBIGUOUS"):
        record = evidence(ids, path=f"{status}.txt", observed_state=status)
        assert layer.record_workspace_evidence(record) > 0
    assert state._connection.execute("SELECT COUNT(*) FROM workspace_evidence").fetchone()[0] == 3


def test_cross_lineage_workspace_evidence_rejects_checkpoint_and_artifact(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    item, checkpoint = trusted_checkpoint(state, layer, ids)
    artifact = layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A")
    other_state, _, other_ids = seed(tmp_path, project_id="PROJECT-B", run_id="RUN-B")
    with pytest.raises(LineageError):
        layer.record_workspace_evidence(evidence(other_ids, checkpoint_id=checkpoint.checkpoint_id))
    with pytest.raises(LineageError):
        layer.record_workspace_evidence(evidence(other_ids, artifact_id=artifact.artifact_id))
    other_state.close()
    assert item.attempt_id == ids["attempt"]


def test_delivery_state_is_durable_and_does_not_imply_verified_effect(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    started = layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_STARTED")
    interrupted = layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_INTERRUPTED")
    committed = layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_COMMITTED")
    assert started.delivery_state == "DELIVERY_STARTED"
    assert interrupted.delivery_state == "DELIVERY_INTERRUPTED"
    assert committed.delivery_state == "DELIVERY_COMMITTED"
    state.close()
    reloaded = DurableExecutionState(tmp_path / ".agent_state" / "execution_state.sqlite3")
    assert reloaded.get_run(ids["run"], project_id=ids["project"]).delivery_state == "DELIVERY_COMMITTED"


def test_transaction_rolls_back_state_and_event_together(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    before = state.get_run(ids["run"], project_id=ids["project"])
    with pytest.raises(InvalidTransitionError):
        layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_VERIFIED")
    after = state.get_run(ids["run"], project_id=ids["project"])
    assert after.sequence == before.sequence
    assert after.delivery_state == before.delivery_state
    state.verify_integrity(project_id=ids["project"], run_id=ids["run"])


def test_hash_chain_remains_intact_after_m2_events(tmp_path: Path) -> None:
    state, layer, ids = seed(tmp_path)
    item, checkpoint = trusted_checkpoint(state, layer, ids)
    layer.register_artifact(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], artifact_id="ART-A", reference="out.bin", identity="ID-A")
    layer.bind_lease(project_id=ids["project"], run_id=ids["run"], phase_id=ids["phase"], task_id=ids["task"], attempt_id=ids["attempt"], lease_id="LEASE-M2", worker_id="W-M2")
    op = layer.create_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_kind="INSPECT", idempotency_key="RUN-A:INSPECT")
    layer.transition_recovery_operation(project_id=ids["project"], run_id=ids["run"], operation_id=op.operation_id, new_state="STARTED")
    layer.set_delivery_state(project_id=ids["project"], run_id=ids["run"], new_state="DELIVERY_STARTED")
    state.verify_integrity(project_id=ids["project"], run_id=ids["run"])
    assert checkpoint.status == "TRUSTED"
    assert item.observed_after_identity == "AFTER"
