import hashlib
import json
from pathlib import Path

import pytest

from durable_execution_evidence import EvidenceLayer, evidence_digest
from durable_execution_state import (
    DurableExecutionState,
    IntegrityError,
    WORKSPACE_SCOPE_VERSION,
    WorkspaceEvidence,
    canonical_workspace_scope,
    reconstruct_workspace_scope,
    workspace_identity,
)
from orchestration import _DurableLifecycleBridge


def test_empty_scope_is_empty_tuple_not_workspace_root():
    assert canonical_workspace_scope(()) == ()


@pytest.mark.parametrize(
    "raw, expected",
    (
        (
            ("b\\nested\\file.txt", "a.txt", "b/nested/file.txt", "./c.txt"),
            ("a.txt", "b/nested/file.txt", "c.txt"),
        ),
        (("z.txt", "a.txt", "z.txt", "a.txt"), ("a.txt", "z.txt")),
        (("a/./b/../c.txt",), ("a/c.txt",)),
    ),
)
def test_scope_is_slash_normalized_sorted_deduplicated_and_canonical(raw, expected):
    assert canonical_workspace_scope(raw) == expected


@pytest.mark.parametrize(
    "value",
    (
        "/absolute.txt",
        "\\absolute.txt",
        "\\\\server\\share\\file.txt",
        "C:\\workspace\\file.txt",
        "C:/workspace/file.txt",
        "../outside.txt",
        "a/../../outside.txt",
        ".",
        "./",
        "",
    ),
)
def test_scope_rejects_absolute_root_escape_and_empty_entries(value):
    with pytest.raises(IntegrityError):
        canonical_workspace_scope((value,))


def test_scope_reconstruction_fails_closed_for_unknown_or_noncanonical_data():
    assert reconstruct_workspace_scope(
        WORKSPACE_SCOPE_VERSION,
        ("a.txt", "b/c.txt"),
    ) == ("a.txt", "b/c.txt")

    with pytest.raises(IntegrityError):
        reconstruct_workspace_scope("workspace-scope-v9", ("a.txt",))

    with pytest.raises(IntegrityError):
        reconstruct_workspace_scope(WORKSPACE_SCOPE_VERSION, None)

    with pytest.raises(IntegrityError):
        reconstruct_workspace_scope(
            WORKSPACE_SCOPE_VERSION,
            ("b.txt", "a.txt"),
        )

    with pytest.raises(IntegrityError):
        reconstruct_workspace_scope(
            WORKSPACE_SCOPE_VERSION,
            ("a\\b.txt",),
        )


def test_legacy_scope_is_not_inferred():
    assert reconstruct_workspace_scope(None, None) is None


def test_identity_semantics_cover_file_directory_and_absent(tmp_path: Path):
    file_path = tmp_path / "file.txt"
    directory = tmp_path / "directory"
    file_path.write_bytes(b"abc")
    directory.mkdir()

    scope = canonical_workspace_scope(
        ("file.txt", "directory", "missing.txt")
    )
    actual = workspace_identity(tmp_path, scope)

    expected_entries = [
        ("directory", "DIRECTORY"),
        (
            "file.txt",
            "sha256:" + hashlib.sha256(b"abc").hexdigest(),
        ),
        ("missing.txt", "ABSENT"),
    ]
    expected = hashlib.sha256(
        json.dumps(
            expected_entries,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    assert actual == expected


def test_in_scope_mutation_changes_identity(tmp_path: Path):
    target = tmp_path / "inside.txt"
    target.write_text("before", encoding="utf-8")
    scope = canonical_workspace_scope(("inside.txt",))

    before = workspace_identity(tmp_path, scope)
    target.write_text("after", encoding="utf-8")
    after = workspace_identity(tmp_path, scope)

    assert before != after


def test_outside_scope_mutation_does_not_change_identity(tmp_path: Path):
    inside = tmp_path / "inside.txt"
    outside = tmp_path / "outside.txt"
    inside.write_text("stable", encoding="utf-8")
    outside.write_text("before", encoding="utf-8")
    scope = canonical_workspace_scope(("inside.txt",))

    before = workspace_identity(tmp_path, scope)
    outside.write_text("after", encoding="utf-8")
    after = workspace_identity(tmp_path, scope)

    assert before == after


def test_evidence_digest_includes_scope_fields():
    base = WorkspaceEvidence(
        project_id="p",
        run_id="r",
        phase_id="ph",
        task_id="t",
        attempt_id="a",
        relative_path=".",
        change_kind="MODIFIED",
        expected_before_identity="before",
        observed_before_identity="before",
        expected_after_identity="after",
        observed_after_identity="after",
        observed_state="PRESENT_COMPLETE",
        checkpoint_id=None,
        artifact_id=None,
        evidence_created_at="2026-01-01T00:00:00+00:00",
        workspace_scope_version=WORKSPACE_SCOPE_VERSION,
        workspace_scope_entries=("a.txt",),
    )
    changed = WorkspaceEvidence(
        **{
            **base.to_dict(),
            "workspace_scope_entries": ("b.txt",),
        }
    )

    assert evidence_digest(base) != evidence_digest(changed)


def test_legacy_evidence_digest_has_no_inferred_scope():
    evidence = WorkspaceEvidence(
        project_id="p",
        run_id="r",
        phase_id="ph",
        task_id="t",
        attempt_id="a",
        relative_path=".",
        change_kind="MODIFIED",
        expected_before_identity="before",
        observed_before_identity="before",
        expected_after_identity="after",
        observed_after_identity="after",
        observed_state="PRESENT_COMPLETE",
        checkpoint_id=None,
        artifact_id=None,
        evidence_created_at="2026-01-01T00:00:00+00:00",
    )

    payload = evidence.to_dict()
    assert payload["workspace_scope_version"] is None
    assert payload["workspace_scope_entries"] is None
    assert evidence_digest(evidence)


def test_m31_persistence_survives_close_reopen_and_reconstructs_exact_scope(
    tmp_path: Path,
):
    database = tmp_path / "state.db"
    source_dir = tmp_path / "src"
    output_file = source_dir / "output.txt"
    source_dir.mkdir()
    output_file.write_text("before", encoding="utf-8")

    state = DurableExecutionState(database)
    bridge = _DurableLifecycleBridge(state, tmp_path)
    bridge.ensure_project()
    run_id = bridge.create_run()
    task_id = "task-1"
    phase_id = f"{run_id}:PHASE:1"
    bridge.accept_plan(run_id, task_id, {"tasks": [{"task_id": task_id}]})
    bridge.start_phase(run_id, phase_id)
    bridge.start_running(run_id)
    bridge.start_task(run_id, phase_id, {"task_id": task_id})
    attempt_id = f"{run_id}:{task_id}:ATTEMPT:1"
    bridge.start_attempt(run_id, phase_id, task_id, attempt_id, "worker-1")

    scope = bridge._workspace_scope(
        ("src\\output.txt", "src", "missing.txt", "src/output.txt")
    )
    before = bridge._workspace_identity_for_scope(scope)

    output_file.write_text("after", encoding="utf-8")
    after = bridge._workspace_identity_for_scope(scope)

    checkpoint_id, evidence_hash, _, _ = bridge.persist_post_execution(
        run_id,
        phase_id,
        task_id,
        attempt_id,
        "raw-checkpoint-1",
        before,
        after,
        bridge._observed_state(scope, tmp_path),
        workspace_scope_entries=scope,
    )

    row = state._connection.execute(
        "SELECT * FROM workspace_evidence "
        "WHERE project_id=? AND run_id=? AND phase_id=? AND task_id=? AND attempt_id=? "
        "ORDER BY evidence_id DESC LIMIT 1",
        (
            bridge.project_id,
            run_id,
            phase_id,
            task_id,
            attempt_id,
        ),
    ).fetchone()

    assert row is not None
    assert row["workspace_scope_version"] == WORKSPACE_SCOPE_VERSION
    assert tuple(json.loads(row["workspace_scope_entries"])) == scope
    assert row["expected_after_identity"] == after

    state.close()

    reopened = DurableExecutionState(database)
    reopened_row = reopened._connection.execute(
        "SELECT * FROM workspace_evidence WHERE evidence_id=?",
        (int(row["evidence_id"]),),
    ).fetchone()

    assert reopened_row is not None
    restored_scope = reconstruct_workspace_scope(
        reopened_row["workspace_scope_version"],
        tuple(json.loads(reopened_row["workspace_scope_entries"])),
    )
    assert restored_scope == scope
    assert workspace_identity(tmp_path, restored_scope) == after
    assert EvidenceLayer._evidence_row_digest(reopened_row) == evidence_hash

    reopened.close()


def test_legacy_row_shape_does_not_infer_scope():
    row = {
        "project_id": "p",
        "run_id": "r",
        "phase_id": "ph",
        "task_id": "t",
        "attempt_id": "a",
        "relative_path": ".",
        "change_kind": "MODIFIED",
        "expected_before_identity": None,
        "observed_before_identity": None,
        "expected_after_identity": None,
        "observed_after_identity": None,
        "observed_state": "ABSENT",
        "checkpoint_id": None,
        "artifact_id": None,
        "evidence_created_at": "2026-01-01T00:00:00+00:00",
    }

    evidence = _DurableLifecycleBridge._evidence_from_row(row)
    assert evidence.workspace_scope_version is None
    assert evidence.workspace_scope_entries is None


def test_workspace_evidence_serialization_contains_scope():
    evidence = WorkspaceEvidence(
        project_id="p",
        run_id="r",
        phase_id="ph",
        task_id="t",
        attempt_id="a",
        relative_path=".",
        change_kind="MODIFIED",
        expected_before_identity="before",
        observed_before_identity="before",
        expected_after_identity="after",
        observed_after_identity="after",
        observed_state="PRESENT_COMPLETE",
        checkpoint_id=None,
        artifact_id=None,
        evidence_created_at="2026-01-01T00:00:00+00:00",
        workspace_scope_version=WORKSPACE_SCOPE_VERSION,
        workspace_scope_entries=("a.txt", "b.txt"),
    )

    payload = evidence.to_dict()
    assert payload["workspace_scope_version"] == WORKSPACE_SCOPE_VERSION
    assert payload["workspace_scope_entries"] == ["a.txt", "b.txt"]
