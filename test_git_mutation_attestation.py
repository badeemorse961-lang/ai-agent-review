from __future__ import annotations

from pathlib import Path

import pytest

from git_mutation_attestation import (
    GitMutationAttestation,
    GitMutationAttestationError,
    attestation_from_dict,
    verify_attestation_binding,
)


def _attestation(tmp_path: Path) -> GitMutationAttestation:
    return GitMutationAttestation(
        task_id="task-1",
        worker_id="worker-1",
        workspace=str(tmp_path.resolve()),
        targets=("calculator.py", "docs/notes.txt"),
        commit_sha="a" * 40,
        object_format="sha1",
        staged_evidence_sha256="b" * 64,
        commit_evidence_sha256="c" * 64,
    )


def test_attestation_round_trips_through_serialized_mapping(tmp_path: Path) -> None:
    original = _attestation(tmp_path)
    restored = attestation_from_dict(original.to_dict())
    assert restored == original


def test_attestation_canonicalizes_target_order_and_separators(tmp_path: Path) -> None:
    attestation = GitMutationAttestation(
        task_id="task-1",
        worker_id="worker-1",
        workspace=str(tmp_path.resolve()),
        targets=("docs\\notes.txt", "calculator.py"),
        commit_sha="a" * 40,
        object_format="sha256",
        staged_evidence_sha256="b" * 64,
        commit_evidence_sha256="c" * 64,
    )
    assert attestation.targets == ("calculator.py", "docs/notes.txt")


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_id", ""),
        ("worker_id", ""),
        ("commit_sha", "z" * 40),
        ("staged_evidence_sha256", "z" * 64),
        ("commit_evidence_sha256", "z" * 64),
    ],
)
def test_attestation_rejects_invalid_identity_or_digest(
    tmp_path: Path, field: str, value: str
) -> None:
    values = _attestation(tmp_path).to_dict()
    values[field] = value
    with pytest.raises(GitMutationAttestationError):
        attestation_from_dict(values)


def test_attestation_rejects_duplicate_targets(tmp_path: Path) -> None:
    values = _attestation(tmp_path).to_dict()
    values["targets"] = ["calculator.py", "calculator.py"]
    with pytest.raises(GitMutationAttestationError, match="duplicate paths"):
        attestation_from_dict(values)


def test_attestation_binding_accepts_exact_transaction_identity(tmp_path: Path) -> None:
    attestation = _attestation(tmp_path)
    verify_attestation_binding(
        attestation,
        task_id="task-1",
        worker_id="worker-1",
        workspace=tmp_path,
        targets=("calculator.py", "docs/notes.txt"),
        commit_sha="a" * 40,
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"task_id": "task-2"},
        {"worker_id": "worker-2"},
        {"commit_sha": "d" * 40},
        {"targets": ("calculator.py",)},
    ],
)
def test_attestation_binding_rejects_identity_drift(
    tmp_path: Path, kwargs: dict[str, object]
) -> None:
    attestation = _attestation(tmp_path)
    binding = {
        "task_id": "task-1",
        "worker_id": "worker-1",
        "workspace": tmp_path,
        "targets": ("calculator.py", "docs/notes.txt"),
        "commit_sha": "a" * 40,
    }
    binding.update(kwargs)
    with pytest.raises(GitMutationAttestationError, match="not bound"):
        verify_attestation_binding(attestation, **binding)


def test_attestation_from_dict_rejects_schema_drift(tmp_path: Path) -> None:
    values = _attestation(tmp_path).to_dict()
    values["schema_version"] = 99
    with pytest.raises(GitMutationAttestationError, match="schema version"):
        attestation_from_dict(values)


def test_attestation_from_dict_rejects_non_list_targets(tmp_path: Path) -> None:
    values = _attestation(tmp_path).to_dict()
    values["targets"] = ("calculator.py",)
    with pytest.raises(GitMutationAttestationError, match="serialized as a list"):
        attestation_from_dict(values)
