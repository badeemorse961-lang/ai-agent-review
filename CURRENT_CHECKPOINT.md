# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`f84b143ef02ebf51f2c81d4c2bd532bb7a9de21c`

PR #45 established and promoted the canonical end-to-end orchestration composition across the existing authority boundaries. PR #47 then promoted the next coherent milestone: Production Runtime Composition & Release Readiness.

## Verified architecture

The repository includes registry-driven leader/worker routing, N-driven pools, runtime connection resilience, project understanding, context building, Central Leader planning, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized redaction, the task-scoped Git mutation control plane, the Execution Gate process boundary, strict persisted mutation-result restoration, immutable transaction attestation, live Git evidence rebinding, machine-validated configuration authority, runtime health/lease state authority, authoritative worker lease binding, validation verdict authority binding, explicit autonomous leader start authorization, live Central Leader lease rebinding, execution-checkpoint identity binding, and canonical orchestration composition.

The canonical architecture remains:

```text
User Goal
  ↓
Project/Documentation Discovery
  ↓
Project Understanding
  ↓
Central Leader
  ↓
Plan / Decomposition
  ↓
Specialist Workers
  ↓
Independent Validation
  ↓
Execution Authorization
  ↓
Execution Gate
  ↓
Checkpoint / Guarded Apply
  ↓
Tests
  ↓
Verification
  ├─ APPROVE
  └─ ROLLBACK → VERIFY
```

The professional desktop Control Center is now an authoritative product requirement, documented in `PRODUCT_UI_SPEC.md` and reflected in `ARCHITECTURE.md`. It is a thin application boundary and cannot become a second execution or mutation authority.

## PR #47 — Production Runtime Composition & Release Readiness

### Implemented

- `production_runtime.py` provides an explicit production bootstrap over the existing Core boundaries.
- `provider_transport.py` provides an OpenAI-compatible HTTP transport with stable connection-ID secret mapping; production transport does not depend on positional secret-list indexing.
- Provider responses remain untrusted planning input; malformed/unusable responses fail closed and provider failures expose only bounded non-secret diagnostics.
- Production worker execution requires explicit authoritative worker lease lookup, isolated checkpoint capability, and the existing TerminalExecutor/TerminalPolicy/ProcessSandbox path; there is no raw-subprocess fallback.
- Python executable policy is portable across versioned launchers such as `python3.12` without weakening the existing rejection of inline `-c`/`-m` execution and shell wrappers.
- CI now includes full regression coverage and a dedicated Windows regression workflow.
- `PRODUCTION_RUNTIME.md` documents the runtime boundary, its explicit dependencies, and the remaining Worker work-product gap.

### Verified

The following are now verified by executable evidence:

- Canonical composition tests: PASS.
- Production runtime/provider focused tests: PASS.
- Repository security audit: PASS.
- Full Windows CI regression: PASS.
- Windows compile: PASS.
- Windows focused runtime/orchestration/provider suite: `17 passed`.
- Windows CI full regression on promotion head: `295 passed, 13 subtests passed`.
- Windows CI diff validation: PASS.
- Real local Windows focused suite: `35 passed`.
- Real local Windows full regression: `294 passed, 1 skipped`.
- Real local Windows `python -m compileall -q .`: PASS.
- Real local Windows `python repository_security_audit.py`: PASS.
- Real local Windows `git diff --check`: PASS.
- Real local Windows worktree: CLEAN.
- Existing provider/router smoke: PASS; healthy Ultra leaders `8`, healthy Super leaders `10`, configured Groq workers `15`, Leader `OR-02`, Worker `GROQ-01`, project files sent `NO`.

The provider/router smoke remains a separate connectivity/failover check and is not treated as proof of the complete canonical production runtime path.

## Partially verified / evidence gaps

### Production runtime end-to-end execution

`production_runtime.py` is implemented and its dependency wiring is covered deterministically, but a complete real production run is not currently verifiable because the repository still does not define an authoritative Worker work-product protocol.

This is therefore **PARTIALLY VERIFIED**, not fully VERIFIED.

### Provider transport live production exercise

The new stable-ID provider transport is covered by deterministic tests and secret-mapping/error-handling tests. The credential-bearing real smoke currently proves the existing provider/router path separately. A dedicated live exercise of the new `provider_transport.py` inside a complete production WorkerAdapter-driven run remains an evidence gap.

This is an **evidence gap**, not evidence of an implementation failure.

## Real implementation/specification gaps

### Worker work-product protocol — OPEN

The Core does not yet define an authoritative model/Worker contract for:

- exact worker command;
- exact execution-scope targets;
- exact `changed_targets`;
- exact `FileChange.old_text` / `new_text` payload;
- validation evidence required for that work product.

The canonical orchestrator validates these fields when provided, but inventing a model-output generation protocol would create a new requirement rather than implement an existing one.

Status: **IMPLEMENTATION/SPECIFICATION GAP**.

### Professional Desktop Control Center — OPEN

`PRODUCT_UI_SPEC.md` is now authoritative. The repository currently has the specification and architecture only; the desktop product implementation is not yet present.

Required future scope includes the application/UI service boundary, Dashboard, Central Leader chat, Projects, Connections & Pools, Run/Plan view, Workers, Evidence & Activity, Git & Changes, Tests & Verification, Safety & Policy Center, Settings/Diagnostics, secure credential workflows, structured UI intents, and Windows end-to-end acceptance.

Status: **IMPLEMENTATION GAP**.

This UI requirement supersedes a terminal-first product assumption. Python/PowerShell remain development, diagnostics, and advanced-operator surfaces rather than the primary end-user interface.

## Safety / acceptance rules

UNKNOWN and unresolved CONFLICT remain safety stops. Confirmed breakage means REPAIR. Model output is untrusted. Secrets remain outside Git history and normal child environments. Generic terminal Git access remains inspection-only. High-risk authority remains explicitly separated. Never use destructive synchronization such as `git clean -fd` or `git reset --hard`.

Git mutation success still requires exact validated targets/content, isolated checkpoint evidence, exact authorization binding, clean post-commit state, and independently verifiable committed-target evidence.

No plan-wide atomic rollback claim is made for multi-task canonical orchestration; task-scoped transactions remain independently governed by their existing mutation control plane.

## Future operational readiness — Dynamic Connection Onboarding & Auto-Assignment

Tracking issue: **#46 — Future readiness: Dynamic Connection Onboarding & Auto-Assignment**.

Current assessment: **CONFIGURATION-DRIVEN ONLY**.

The repository already supports variable-length registry-defined leader/worker pools, uniqueness and assignment validation, provider consistency checks, runtime health separation, and router-side exclusion of unavailable connections. This proves configuration-driven expansion, not automatic onboarding.

Not currently verified as one operational capability: capability discovery for newly added connections, deterministic classification, automatic registry/pool insertion without manual registry maintenance, onboarding health admission, and automatic quarantine/re-admission lifecycle.

This remains future work and is not part of the PR #47 acceptance.

## Previously promoted milestones

PR #24 — OS-level workspace mutation locking.

PR #25 — NUL-delimited staged-index evidence hardening.

PR #27 — authoritative integration of locking and staged evidence.

PR #28 — cross-process lock exclusion/crash-release evidence.

PR #30 — immutable task-scoped transaction attestation primitive.

PR #31 — attestation integration into authoritative Git mutation results.

PR #32 — strict whole-result restoration boundary.

PR #33 — live Git evidence rebinding.

PR #34 — machine-validated configuration registry authority.

PR #36 — runtime health and lease state authority hardening.

PR #38 — authoritative worker lease binding at the execution boundary.

PR #39 — validation verdict authority binding at mutation admission.

PR #40 — explicit autonomous leader start authorization at the Central Leader boundary.

PR #41 — live Central Leader lease rebinding after model transport.

PR #42 — execution-checkpoint identity binding at mutation authorization.

PR #43 — restored GitHub Actions security-audit dependency evidence.

PR #45 — canonical end-to-end orchestration composition and deterministic integration acceptance.

PR #47 — production runtime composition and release-readiness evidence.

## Current readiness

Core architecture: **VERIFIED**.

Canonical integration: **VERIFIED**.

Regression/security/runtime integrity: **VERIFIED by current evidence**.

Real Windows runtime validation of the accepted PR #47 code path: **VERIFIED by local Windows execution plus Windows CI**.

Production runtime end-to-end execution: **PARTIALLY VERIFIED** because the Worker work-product protocol is not defined.

Professional Desktop Control Center: **IMPLEMENTATION GAP** because only the authoritative specification/architecture exists.

Dynamic Connection Onboarding & Auto-Assignment: **CONFIGURATION-DRIVEN ONLY**.

## Closest real acceptance gate before final project readiness

The project is **not final-release ready**.

The next real project-level acceptance gate is the **Professional Desktop Control Center milestone**, but it must be implemented as a thin application boundary over the already verified Core. Its completion gate is explicitly real Windows end-to-end acceptance covering the authoritative UI functional criteria, security/redaction, canonical orchestration visibility, provider/connection management, SAFE_STOP behavior, evidence rendering, and recovery/failover behavior.

Separately, the Worker work-product protocol remains an upstream specification/implementation dependency for a truly end-to-end autonomous production run. It should be formalized before claiming full production runtime completion rather than being invented implicitly by the UI layer.

## Promotion rule

For each architectural/product milestone:

```text
complete grouped implementation
    ↓
focused deterministic tests
    ↓
full regression
    ↓
security / integrity / diff verification
    ↓
real Windows acceptance
    ↓
merge to main
    ↓
update this checkpoint on main
```
