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

## Remaining production gap

The repository still does not define an authoritative model-output contract for a Worker to determine:

- the exact command to execute;
- execution-scope target paths;
- exact `changed_targets`;
- exact `FileChange.old_text` / `new_text` content;
- the validation evidence required for that work product.

The canonical orchestrator already enforces these fields when supplied, but inventing their model-level generation protocol would create new requirements rather than implement the existing specification.

Therefore this milestone establishes the production bootstrap and provider boundary while leaving the Worker work-product protocol as an explicit **implementation/specification gap**.

## Release evidence

The release gate must combine compile, focused runtime tests, full regression, security audit, Windows regression evidence, and a real provider smoke in the credential-bearing local environment. CI must not receive local provider secrets.
