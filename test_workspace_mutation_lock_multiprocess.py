from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from workspace_mutation_lock import WorkspaceMutationLock, WorkspaceMutationLockError

_WORKER_SCRIPT = r'''
import sys
import time
from pathlib import Path
from workspace_mutation_lock import WorkspaceMutationLock
workspace = Path(sys.argv[1])
mode = sys.argv[2]
if mode == "hold":
    with WorkspaceMutationLock(workspace):
        print("LOCKED", flush=True)
        time.sleep(float(sys.argv[3]))
elif mode == "probe":
    try:
        with WorkspaceMutationLock(workspace):
            print("ACQUIRED", flush=True)
    except Exception as exc:
        print(f"REJECTED:{type(exc).__name__}:{exc}", flush=True)
elif mode == "crash":
    with WorkspaceMutationLock(workspace):
        print("LOCKED", flush=True)
        raise SystemExit(37)
else:
    raise SystemExit(2)
'''


def _run_worker(workspace: Path, mode: str, *args: str) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent)
    return subprocess.Popen(
        [sys.executable, "-c", _WORKER_SCRIPT, str(workspace), mode, *args],
        cwd=workspace,
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _readline(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    return process.stdout.readline().strip()


def test_second_process_cannot_acquire_active_workspace_lock(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    holder = _run_worker(workspace, "hold", "2")
    try:
        assert _readline(holder) == "LOCKED"
        probe = _run_worker(workspace, "probe")
        stdout, stderr = probe.communicate(timeout=5)
        assert probe.returncode == 0
        assert stdout.strip().startswith("REJECTED:WorkspaceMutationLockError:")
        assert stderr == ""
    finally:
        holder.terminate()
        holder.communicate(timeout=5)


def test_crashed_process_releases_workspace_lock(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    crashed = _run_worker(workspace, "crash")
    assert _readline(crashed) == "LOCKED"
    stdout, stderr = crashed.communicate(timeout=5)
    assert crashed.returncode == 37
    assert stdout == ""
    assert stderr == ""
    with WorkspaceMutationLock(workspace):
        pass


def test_lock_rejects_lock_path_collision_with_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    lock = WorkspaceMutationLock(workspace)
    lock.path.mkdir()
    with pytest.raises(WorkspaceMutationLockError):
        with lock:
            pass
