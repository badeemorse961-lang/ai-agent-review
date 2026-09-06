# Workspace Mutation Lock

The task-scoped Git mutation transaction requires one exclusive owner per canonical workspace.

## Lock contract

`WorkspaceMutationLock` derives a stable lock pathname from the resolved workspace root and uses an operating-system advisory file lock on that file.

The lock file is persistent. It is not deleted on release and is not used as a PID-based ownership marker. A process owns the critical section only while it holds the OS-level lock.

This removes the unsafe `check PID → unlink stale file → recreate file` sequence. A crashed process releases its kernel-managed lock automatically, so a later transaction can acquire the existing lock file without a stale-lock race.

The implementation fails closed when the lock cannot be acquired or ownership metadata cannot be recorded. The lock itself does not grant Git, filesystem, network, shell, or authorization authority; it only serializes the existing mutation transaction.

## Platform behavior

On Windows the implementation uses the standard-library `msvcrt` file-locking primitive. On POSIX systems it uses `fcntl.flock` with non-blocking exclusive acquisition.

The lock key is derived from the canonical workspace path, so unrelated workspaces receive independent lock files while concurrent transactions for the same workspace contend on the same operating-system lock.

## Security boundary

The lock is an ordering/concurrency boundary, not an authorization boundary. Existing `ExecutionAuthorizationBoundary`, `GitMutationPolicy`, `ProcessSandbox`, staging verification, commit verification, and rollback/evidence-preservation semantics remain authoritative.
