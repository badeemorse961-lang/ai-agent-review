# M3.3 — Production Worker Adapter Scope

The remaining production gap is the real WorkerAdapter path for the canonical orchestrator. The adapter must consume bounded worker context and authoritative lease identity, obtain a real Groq worker proposal, produce a validated WorkerExecutionSpec, then rely on the existing WorkerExecutionBoundary, IndependentValidator, WorkerWorkProduct, and ExecutionAuthorizationBoundary / Execution Gate.

The implementation must not grant authority to model output, bypass execution/validation/authorization boundaries, expose raw credentials, or use unbounded shell execution.
