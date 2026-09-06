from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


class WorkspaceMutationLockError(RuntimeError):
    """Raised when an exclusive workspace mutation lock cannot be acquired."""


class WorkspaceMutationLock:
    """Cross-process advisory lock keyed to one canonical workspace.

    The lock file is persistent by design. Ownership is represented by an
    operating-system file lock rather than by create/delete PID races, so a
    crashed owner releases the lock automatically when its process ends.
    """

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        digest = hashlib.sha256(
            str(self.workspace_root).encode("utf-8")
        ).hexdigest()[:24]
        self.path = (
            Path(tempfile.gettempdir())
            / f"ai-agent-git-mutation-{digest}.lock"
        )
        self._handle = None

    def __enter__(self) -> "WorkspaceMutationLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            self._acquire(handle)
            self._handle = handle
            self._write_owner_pid(handle)
            return self
        except WorkspaceMutationLockError:
            raise
        except OSError as exc:
            raise WorkspaceMutationLockError(
                f"Unable to initialize the workspace mutation lock: {exc}"
            ) from exc

    def _acquire(self, handle) -> None:
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                try:
                    handle.close()
                except OSError:
                    pass
                raise WorkspaceMutationLockError(
                    "Another task-scoped Git mutation is already active for this workspace"
                ) from exc
            return

        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            try:
                handle.close()
            except OSError:
                pass
            raise WorkspaceMutationLockError(
                "Another task-scoped Git mutation is already active for this workspace"
            ) from exc

    @staticmethod
    def _write_owner_pid(handle) -> None:
        try:
            handle.seek(0)
            handle.truncate(0)
            handle.write(str(os.getpid()).encode("ascii"))
            handle.flush()
        except OSError as exc:
            raise WorkspaceMutationLockError(
                f"Unable to record workspace mutation lock ownership: {exc}"
            ) from exc

    def __exit__(self, *_: object) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                handle.close()
            except OSError:
                pass
