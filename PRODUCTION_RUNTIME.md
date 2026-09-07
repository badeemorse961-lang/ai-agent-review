# Production Runtime Boundary

## Purpose

`production_runtime.py` is the explicit bootstrap for running the approved canonical orchestration composition with real repository boundaries. It does not replace those boundaries and does not invent worker authority.

## Composition

```text
ProjectUnderstandingPipeline
        ↓
CentralLeader + LeaderRouter + provider transport
        ↓
PlanDecomposer
        ↓
WorkerDispatcher + WorkerRouter
        ↓
WorkerExecutionBoundary + explicit checkpoint hook
        ↓
IndependentValidator
        ↓
WorkerWorkProduct
        ↓
ExecutionAuthorizationBoundary
        ↓
ExecutionGate
```

The bootstrap requires three runtime capabilities that materially affect safe execution:

1. a provider transport for leader planning;
2. an explicit worker checkpoint hook;
3. a concrete `WorkerAdapter` that returns the already-defined `WorkerExecutionSpec` and validation evidence.

Missing capabilities are configuration errors rather than implicit fallbacks.

## Provider transport

`provider_transport.py` provides a concrete OpenAI-compatible HTTP transport for the existing OpenRouter and Groq endpoints. The account identity comes from the authoritative router lease, and production secret lookup is keyed by the stable connection ID.

The transport deliberately does not use positional secret-list mapping. This preserves the N-driven expansion invariant and prevents an account such as `OR-21` from depending on the twentieth element of an unrelated list.

Provider responses remain untrusted planning input. Invalid JSON or unusable response shapes fail closed. Provider errors expose only bounded non-secret diagnostics.

## Worker work-product protocol

The authoritative worker output contract is `WorkerWorkProduct`, documented in `WORKER_WORK_PRODUCT_PROTOCOL.md` and implemented by `worker_work_product.py`.

The contract binds:

- task and leased worker identity;
- the exact argument-array command;
- bounded execution targets;
- exact `changed_targets`;
- matching `FileChange.path`, `old_text`, and `new_text`;
- task-required validation criteria;
- passed independent validation evidence bound to the execution checkpoint;
- bounded execution result/status;
- bounded failure metadata where execution fails or reaches a safety stop.

The work product is created by the Core only after worker execution and independent validation succeed. It is therefore evidence consumed by the existing authorization boundary, not a new authority. Raw stdout/stderr are intentionally excluded from the work-product schema.

## Production completion status

The production bootstrap and provider boundary are implemented. The Worker work-product protocol is now explicitly defined and integrated into canonical orchestration.

A complete real production WorkerAdapter-driven run using the protocol still requires live provider/worker execution evidence. That live exercise is an acceptance/evidence gate, not a reason to bypass the deterministic contract tests.

## Release evidence

The release gate must combine compile, focused runtime tests, full regression, security audit, Windows regression evidence, and a real provider smoke in the credential-bearing local environment. CI must not receive local provider secrets.
