# Workspace Mutation Concurrency Evidence

`WorkspaceMutationLock` is an OS-level concurrency boundary for the Git mutation critical section. Its ownership is represented by the kernel lock, not by a PID file or create/delete race.

## Required behavior

```text
process A acquires lock
        ↓
process B attempts same workspace lock
        ↓
B must fail closed while A owns the lock
        ↓
A exits normally or crashes
        ↓
kernel releases the lock
        ↓
next process may acquire the lock
```

The lock file is persistent and is only the addressable kernel-lock object. Its contents are diagnostic metadata, not authority and not proof of ownership.

## Cross-process verification

`test_workspace_mutation_lock_multiprocess.py` exercises the boundary with real child Python processes rather than two lock objects in one process. The tests cover active-owner exclusion, crash-release behavior, and lock-path initialization collisions.

These tests do not grant any new mutation capability. They verify that the existing mutation critical section remains serialized across independent processes.

## Platform contract

- Windows uses `msvcrt.locking` for non-blocking exclusive acquisition.
- POSIX uses `fcntl.flock` with `LOCK_EX | LOCK_NB`.
- A failed acquisition is translated to `WorkspaceMutationLockError` and is fail-closed at the Git mutation adapter.
- A process crash releases the kernel-managed lock automatically.
