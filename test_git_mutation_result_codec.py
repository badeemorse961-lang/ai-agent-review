from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from git_mutation_attestation import GitMutationAttestation
from git_mutation_executor import GitMutationResult, GitRepositorySnapshot
from git_mutation_result_codec import (
    GitMutationResultRestoreError,
    restore_git_mutation_result,
    verify_restored_attestation,
)


def make_payload(tmp_path: Path) -> dict[str, object]:
    workspace = tmp_path.resolve()
    commit_sha = "a" * 40
    attestation = GitMutationAttestation(
        task_id="task-codec",
        worker_id="worker-codec",
        workspace=str(workspace),
        targets=("calculator.py",),
        commit_sha=commit_sha,
        object_format="sha1",
        staged_evidence_sha256="b" * 64,
        commit_evidence_sha256="c" * 64,
    )
    result = GitMutationResult(
        task_id="task-codec",
        worker_id="worker-codec",
        targets=("calculator.py",),
        commit_sha=commit_sha,
        staged=True,
        committed=True,
        verified=True,
        before=GitRepositorySnapshot(
            branch="main",
            status_lines=(),
            staged_paths=(),
            worktree_paths=(),
            head_sha="d" * 40,
        ),
        after=GitRepositorySnapshot(
            branch="main",
            status_lines=(),
            staged_paths=(),
            worktree_paths=(),
            head_sha=commit_sha,
        ),
        commit_message_sha256="e" * 64,
        attestation=attestation,
    )
    return result.to_dict()


def test_restore_round_trip_preserves_verified_result(tmp_path: Path) -> None:
    payload = make_payload(tmp_path)
    restored = restore_git_mutation_result(payload)

    assert restored.to_dict() == payload
    verify_restored_attestation(restored)


def test_restore_rejects_result_task_tampering(tmp_path: Path) -> None:
    payload = make_payload(tmp_path)
    payload["task_id"] = "attacker-task"

    with pytest.raises(GitMutationResultRestoreError, match="task identity"):
        restore_git_mutation_result(payload)


def test_restore_rejects_result_worker_tampering(tmp_path: Path) -> None:
    payload = make_payload(tmp_path)
    payload["worker_id"] = "attacker-worker"

    with pytest.raises(GitMutationResultRestoreError, match="worker identity"):
        restore_git_mutation_result(payload)


def test_restore_rejects_target_set_tampering(tmp_path: Path) -> None:
    payload = make_payload(tmp_path)
    payload["targets"] = ["other.py"]

    with pytest.raises(GitMutationResultRestoreError, match="target set"):
        restore_git_mutation_result(payload)


def test_restore_rejects_commit_identity_tampering(tmp_path: Path) -> None:
    payload = make_payload(tmp_path)
    payload["commit_sha"] = "f" * 40

    with pytest.raises(GitMutationResultRestoreError, match="post-commit HEAD"):
        restore_git_mutation_result(payload)


def test_restore_rejects_post_commit_head_mismatch(tmp_path: Path) -> None:
    payload = make_payload(tmp_path)
    after = dict(payload["after"])
    after["head_sha"] = "1" * 40
    payload["after"] = after

    with pytest.raises(GitMutationResultRestoreError, match="post-commit HEAD"):
        restore_git_mutation_result(payload)


def test_restore_rejects_verified_result_without_attestation(tmp_path: Path) -> None:
    payload = make_payload(tmp_path)
    payload["attestation"] = None

    with pytest.raises(GitMutationResultRestoreError, match="transaction attestation"):
        restore_git_mutation_result(payload)


def test_restore_rejects_non_boolean_flags(tmp_path: Path) -> None:
    payload = make_payload(tmp_path)
    payload["verified"] = 1

    with pytest.raises(GitMutationResultRestoreError, match="verified must be a boolean"):
        restore_git_mutation_result(payload)


def test_restore_rejects_schema_drift(tmp_path: Path) -> None:
    payload = make_payload(tmp_path)
    payload["schema_version"] = 99

    with pytest.raises(GitMutationResultRestoreError, match="schema version"):
        restore_git_mutation_result(payload)


def test_verify_restored_attestation_rejects_modified_object(tmp_path: Path) -> None:
    payload = make_payload(tmp_path)
    result = restore_git_mutation_result(payload)
    assert result.attestation is not None
    altered = replace(result, attestation=replace(result.attestation, worker_id="worker-other"))

    with pytest.raises(GitMutationResultRestoreError, match="worker identity"):
        verify_restored_attestation(altered)
