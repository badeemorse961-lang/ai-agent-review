# M3.3 — Production Worker Adapter Scope

## Objective
Close the remaining production execution gap after M3.2 by providing a real WorkerAdapter path for the canonical orchestrator without weakening any existing authority boundary.

## Required flow

```text
validated task + authoritative worker lease
        ↓
bounded worker context/source selection
        ↓
Groq worker transport
        ↓
validated WorkerExecutionSpec
        ↓
WorkerExecutionBoundary
        ↓
IndependentValidator
        ↓
WorkerWorkProduct
        ↓
ExecutionAuthorizationBoundary / Execution Gate
```

## Current verified gap
- `WorkerAdapter` exists only as an explicit orchestration protocol/dependency.
- Production runtime requires an injected `worker_adapter` and intentionally does not provide a fallback.
- Existing `provider_transport.py` currently implements OpenAI-compatible leader transport; it does not provide a worker transport.
- `ContextBuilder` intentionally excludes source contents, so worker execution currently has no bounded source-selection/input contract for generating real `FileChange` records.
- Tests use `StubWorkerAdapter`; these are not production execution evidence.

## Boundaries

M3.3 must not:
- grant execution authority to model output;
- bypass `WorkerExecutionBoundary`;
- bypass `IndependentValidator`;
- bypass `ExecutionAuthorizationBoundary` or `ExecutionGate`;
- print or persist raw credentials;
- use arbitrary shell wrappers or unbounded commands;
- modify `CURRENT_CHECKPOINT.md` until the milestone is formally promoted.

## Acceptance target

A real local Windows provider/worker run must prove that an authoritative leased Groq worker can produce a bounded `WorkerExecutionSpec`, execute through the existing guarded boundary, pass independent validation, produce an authoritative `WorkerWorkProduct`, and reach the existing authorization/gate path without raw-secret leakage.
