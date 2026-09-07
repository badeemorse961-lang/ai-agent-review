# Canonical Orchestration Composition

## Purpose

`orchestration.py` is the canonical sequencing boundary for autonomous project work. It composes existing safety boundaries; it does not replace or weaken them.

```text
ProjectUnderstandingAdapter
        ↓
CentralLeader
        ↓
PlanDecomposer
        ↓
WorkerDispatcher
        ↓
WorkerExecutionBoundary
        ↓
IndependentValidator
        ↓
ExecutionAuthorizationBoundary
        ↓
ExecutionGate
        ↓
verified task transaction
```

The provider/router smoke test remains separate and is intentionally not the canonical project-execution path.

## Authority ownership

- Project understanding supplies evidence and bounded planning context.
- `CentralLeader` owns leader routing and live leader-lease rebinding.
- `PlanDecomposer` validates untrusted leader output into a task DAG.
- `WorkerDispatcher` owns authoritative worker assignment and leases.
- `WorkerExecutionBoundary` owns command-policy and process-sandbox admission.
- `IndependentValidator` owns the independent execution verdict boundary.
- `ExecutionAuthorizationBoundary` owns internal promotion to mutation authority.
- `ExecutionGate` owns checkpoint/apply/test/approve-or-rollback semantics.
- The coordinator owns only ordering, composition, and lease cleanup.

No adapter output is treated as authorization.

## Worker adapter contract

A `WorkerAdapter` returns a `WorkerExecutionSpec` containing:

- an argument-array command;
- execution-scope target paths;
- the exact `changed_targets` proposed for mutation;
- matching `FileChange` records;
- optional explicitly declared external resources.

`changed_targets` must equal the `FileChange.path` set. The coordinator rejects mismatches before execution.

The worker adapter also supplies validation evidence through the existing `IndependentValidator` hook. The validator adds the actual execution checkpoint identity to the evidence; callers cannot substitute a different checkpoint identity.

## Read-only tasks

A worker task may declare no `changed_targets` and no `FileChange` records. Such a task still crosses worker execution and independent validation, but no mutation authorization or Execution Gate transaction is invoked because there is no mutation to authorize.

## Multi-task semantics

Tasks execute in deterministic topological order. Worker leases are acquired by `WorkerDispatcher` and are released for the whole orchestration attempt in a `finally` block.

The current coordinator does **not** claim plan-wide atomic rollback across multiple already-approved task transactions. Each mutating task is an independent `ExecutionGate` transaction. A later task failure stops the orchestration without fabricating a rollback of earlier approved transactions.

This preserves evidence and avoids adding an unproven cross-task transaction authority.

## Production adapter requirement

The coordinator does not embed provider SDK calls, secret loading, shell execution, or file mutation logic. A production integration must supply the leader transport through `CentralLeader` and a concrete `WorkerAdapter` implementation through dependency injection.

Deterministic adapters are used by `test_orchestration.py` so the integration suite exercises the real routing, planning, dispatch, worker-execution, independent-validation, and execution-authorization boundaries without external provider calls.

## Safety stops covered by the composition

The integration suite covers unauthorized project state, live worker-lease rebinding immediately before launch, failed independent validation, changed-target mismatch, validation identity mismatch at mutation admission, truncated execution output, and missing execution checkpoint identity.

Existing unit suites remain authoritative for the lower-level checkpoint, lease, target, Git, process, redaction, and rollback invariants.
