from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import pytest

from workspace_mutation_lock import WorkspaceMutationLock, WorkspaceMutationLockError


def test_lock_is_exclusive_within_one_process(tmp_path: Path) -> None:
    first = WorkspaceMutationLock(tmp_path)
    second = WorkspaceMutationLock(tmp_path)

    with first:
        assert first.path.exists()
        with pytest.raises(WorkspaceMutationLockError, match="already active"):
            with second:
                pass

    assert first.path.exists()


def _child_try_lock(workspace: str, queue) -> None:
    try:
        with WorkspaceMutationLock(Path(workspace)):
            queue.put("acquired")
    except WorkspaceMutationLockError:
        queue.put("blocked")


def _child_hold_lock(workspace: str, queue) -> None:
    try:
        with WorkspaceMutationLock(Path(workspace)):
            queue.put("acquired")
            queue.get()
    except WorkspaceMutationLockError:
        queue.put("blocked")


def test_lock_is_exclusive_across_processes(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()

    with WorkspaceMutationLock(tmp_path):
        child = context.Process(
            target=_child_try_lock,
            args=(str(tmp_path), queue),
        )
        child.start()
        child.join(10)
        assert child.exitcode == 0
        assert queue.get(timeout=2) == "blocked"


def test_lock_is_released_when_owner_process_exits(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    child = context.Process(
        target=_child_hold_lock,
        args=(str(tmp_path), queue),
    )
    child.start()
    assert queue.get(timeout=5) == "acquired"

    child.terminate()
    child.join(10)
    assert child.exitcode is not None

    with WorkspaceMutationLock(tmp_path):
        pass


def test_reuses_existing_lock_file_without_pid_reclamation(tmp_path: Path) -> None:
    first = WorkspaceMutationLock(tmp_path)
    first.path.parent.mkdir(parents=True, exist_ok=True)
    stale_pid = os.getpid() + 1000000
    first.path.write_text(str(stale_pid), encoding="ascii")

    with first:
        pass

    assert first.path.exists()
    assert first.path.read_text(encoding="ascii") == str(os.getpid())


def test_lock_path_is_workspace_specific(tmp_path: Path) -> None:
    first = WorkspaceMutationLock(tmp_path / "a")
    second = WorkspaceMutationLock(tmp_path / "b")
    assert first.path != second.path
