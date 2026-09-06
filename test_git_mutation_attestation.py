from __future__ import annotations

from pathlib import Path

import pytest

from git_mutation_attestation import (
    GitMutationAttestation,
    GitMutationAttestationError,
    SCHEMA_VERSION,
    attestation_from_dict,
    verify_attestation_binding,
)


def make_attestation(workspace: Path | None = None) -> GitMutationAttestation:
    root = workspace or Path.cwd()
    return GitMutationAttestation(
        task_id="task-1",
        worker_id="worker-1",
        workspace=str(root.resolve()),
        targets=("calculator.py", "README.md"),
        commit_sha="a" * 40,
        object_format="sha1",
        staged_evidence_sha256="b" * 64,
        commit_evidence_sha256="c" * 64,
    )


def test_attestation_is_frozen_and_normalized() -> None:
    attestation = make_attestation()
    assert attestation.targets == ("README.md", "calculator.py")
    with pytest.raises(AttributeError):
        attestation.task_id = "other"  # type: ignore[misc]


def test_round_trip_serialization_is_exact() -> None:
    original = make_attestation()
    restored = attestation_from_dict(original.to_dict())
    assert restored == original
    assert restored.to_dict()["schema_version"] == SCHEMA_VERSION


def test_binding_accepts_matching_execution_identity(tmp_path: Path) -> None:
    attestation = make_attestation(tmp_path)
    verify_attestation_binding(
        attestation,
        task_id="task-1",
        worker_id="worker-1",
        workspace=tmp_path,
        targets=("calculator.py", "README.md"),
        commit_sha="a" * 40,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_id", ""),
        ("worker_id", ""),
        ("commit_sha", "g" * 40),
        ("staged_evidence_sha256", "b" * 63),
        ("commit_evidence_sha256", "c" * 65),
    ],
)
def test_invalid_attestation_fields_fail_closed(
    field: str,
    value: str,
) -> None:
    values = {
        "task_id": "task-1",
        "worker_id": "worker-1",
        "workspace": str(Path.cwd().resolve()),
        "targets": ("calculator.py",),
        "commit_sha": "a" * 40,
        "object_format": "sha1",
        "staged_evidence_sha256": "b" * 64,
        "commit_evidence_sha256": "c" * 64,
    }
    values[field] = value
    with pytest.raises(GitMutationAttestationError):
        GitMutationAttestation(**values)  # type: ignore[arg-type]


def test_sha256_commit_identity_requires_64_hex_characters() -> None:
    attestation = GitMutationAttestation(
        task_id="task-1",
        worker_id="worker-1",
        workspace=str(Path.cwd().resolve()),
        targets=("calculator.py",),
        commit_sha="a" * 64,
        object_format="sha256",
        staged_evidence_sha256="b" * 64,
        commit_evidence_sha256="c" * 64,
    )
    assert len(attestation.commit_sha) == 64


def test_deserialization_rejects_schema_drift() -> None:
    payload = make_attestation().to_dict()
    payload["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(GitMutationAttestationError, match="schema version"):
        attestation_from_dict(payload)


def test_deserialization_rejects_non_list_targets() -> None:
    payload = make_attestation().to_dict()
    payload["targets"] = "calculator.py"
    with pytest.raises(GitMutationAttestationError, match="serialized as a list"):
        attestation_from_dict(payload)


def test_binding_rejects_task_identity_drift(tmp_path: Path) -> None:
    attestation = make_attestation(tmp_path)
    with pytest.raises(GitMutationAttestationError, match="not bound"):
        verify_attestation_binding(
            attestation,
            task_id="task-2",
            worker_id="worker-1",
            workspace=tmp_path,
            targets=("calculator.py", "README.md"),
            commit_sha="a" * 40,
        )


def test_binding_rejects_commit_identity_drift(tmp_path: Path) -> None:
    attestation = make_attestation(tmp_path)
    with pytest.raises(GitMutationAttestationError, match="not bound"):
        verify_attestation_binding(
            attestation,
            task_id="task-1",
            worker_id="worker-1",
            workspace=tmp_path,
            targets=("calculator.py", "README.md"),
            commit_sha="d" * 40,
        )


def test_duplicate_targets_fail_before_attestation_construction() -> None:
    with pytest.raises(GitMutationAttestationError, match="duplicate"):
        GitMutationAttestation(
            task_id="task-1",
            worker_id="worker-1",
            workspace=str(Path.cwd().resolve()),
            targets=("calculator.py", "calculator.py"),
            commit_sha="a" * 40,
            object_format="sha1",
            staged_evidence_sha256="b" * 64,
            commit_evidence_sha256="c" * 64,
        )
