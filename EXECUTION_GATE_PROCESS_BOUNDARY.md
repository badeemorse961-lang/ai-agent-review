# Execution Gate Process Boundary

## Purpose

The Execution Gate is the final local transaction controller for model-proposed workspace changes. Its test phase must not create a second, weaker process-execution path.

The gate therefore delegates test-process launch to `ExecutionGateProcessRunner`, which composes the existing `WorkspaceResourcePolicy` and `ProcessSandbox` layers.

## Security boundary

The gate-owned runner has one explicit tool authority: the resolved `pytest` executable discovered from the active environment.

The runner inherits the shared process guarantees:

- explicit absolute tool allowlisting
- active workspace as the working directory
- shell-free argument execution
- process-group containment
- bounded execution time
- bounded stdout/stderr
- secret-redacted process output
- fail-closed behavior when the approved test tool cannot be resolved

The runner does not add filesystem mutation authority, remote access, Git mutation, or shell interpretation.

## Why the gate still owns test semantics

`ExecutionGate` remains responsible for deciding what a test result means for the transaction:

`PASS -> APPROVED`

`FAIL/TIMEOUT -> ROLLBACK -> RETEST -> VERIFIED_AFTER_ROLLBACK`

The process boundary only controls how the test command is launched and contained. It does not decide whether a proposed mutation is authorized, nor does it replace the checkpoint, rollback, or final transaction state machine.

## Command contract

The gate invokes pytest as an explicit executable command equivalent to:

```text
pytest -q
```

The executable itself is resolved to an absolute path and allowlisted inside a workspace-scoped `WorkspaceResourcePolicy`. The public `TestResult.command` retains the stable logical command name rather than exposing machine-specific executable paths.

Python's `-m` and `-c` shortcuts are not used by this execution path.

## Failure behavior

If pytest cannot be resolved, if the process boundary refuses launch, or if the process times out, the condition is surfaced as a gate test-execution failure rather than silently bypassing the process sandbox.

No raw `subprocess.run()` fallback exists in the gate test path.

## Scope

This boundary hardens execution of gate-owned tests only. The existing Execution Gate checkpoint/apply/rollback authority remains unchanged, and the dedicated Git Mutation Control Plane remains separately responsible for local Git `stage` and `commit` operations.
