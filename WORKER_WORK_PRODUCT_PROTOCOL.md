# Worker Work-Product Protocol

## Purpose

The Worker Work-Product Protocol defines the typed boundary between a worker execution attempt and the Core's authoritative evidence model.

The worker/model remains untrusted. A worker proposal is not authorization. `WorkerWorkProduct` is authoritative only after the existing execution boundary has produced an execution result and the existing `IndependentValidator` has produced passed validation evidence bound to that execution checkpoint.

## Authority flow

```text
Worker/model proposal
        ↓
WorkerExecutionSpec
        ↓
WorkerExecutionBoundary
        ↓
ExecutionResult + isolated checkpoint
        ↓
IndependentValidator
        ↓
passed validation evidence
        ↓
WorkerWorkProduct
        ↓
ExecutionAuthorizationBoundary / Execution Gate
```

The protocol does not create a new execution or mutation authority. It makes the already-required worker output explicit, typed, deterministic, and safe to consume by later layers.

## Required fields

Each authoritative `WorkerWorkProduct` contains:

- `task_id` — authoritative task identity;
- `worker_id` — authoritative leased worker identity;
- `command` — exact argument-array command used for execution;
- `execution_targets` — exact bounded execution-scope paths;
- `changed_targets` — exact target paths proposed for mutation;
- `changes` — matching `FileChange` records containing `path`, `old_text`, and `new_text`;
- `required_validation` — the task's required acceptance/validation criteria;
- `validation_evidence` — the independent validator evidence, including the execution checkpoint identity;
- `execution_result` — bounded execution status/evidence such as return code, timeout/truncation state, success state, and checkpoint identity;
- `status` — deterministic work-product state;
- `failure` — bounded failure metadata when execution fails or reaches a safety stop.

## Integrity rules

The Core constructs the authoritative work product only after independent validation succeeds.

The following bindings are mandatory:

1. `task_id` must match the execution request.
2. `worker_id` must match the authoritative worker assignment and execution request.
3. `changed_targets` must equal the `FileChange.path` set.
4. Work-product targets must remain within the request workspace and reject symlink/junction escapes.
5. Validation evidence must attest `passed=True`.
6. The validation checkpoint must match the execution checkpoint.
7. The execution result is summarized rather than copied wholesale.
8. Raw stdout/stderr are not fields of the authoritative work product because they can contain untrusted or sensitive material.
9. A successful work product has `status=SUCCEEDED` and no failure object.
10. Failed or unsafe execution may be represented with `status=FAILED` or `status=SAFE_STOP` and bounded failure metadata; such a product is evidence, not authorization.

## Relationship to mutation

`WorkerWorkProduct` does not replace `ExecutionAuthorizationBoundary`, `ExecutionGate`, or the task-scoped Git mutation control plane.

For a mutating task, the existing path remains:

```text
passed validation
  +
isolated checkpoint
  +
exact FileChange set
  +
authoritative execution/worker identity
  ↓
ExecutionAuthorizationBoundary
  ↓
ExecutionGate / Git mutation control plane
```

The protocol therefore closes the work-product contract without weakening any existing mutation authority.

## Failure semantics

Failure classification is deterministic:

- non-zero return code without timeout/truncation → `FAILED` / `EXECUTION_FAILED`;
- timeout or truncated output → `SAFE_STOP` / `EXECUTION_SAFE_STOP`.

Failure messages are bounded. Rich raw process output remains behind the existing execution/redaction boundaries and is not embedded in the authoritative work-product evidence.

## Versioning

`schema_version` is `1` for the initial protocol. Changes to the wire shape require tests and documentation updates before promotion.
