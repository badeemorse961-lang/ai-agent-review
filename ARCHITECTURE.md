# AI-Agent Architecture Baseline

## Purpose
The AI-Agent is an autonomous coding/orchestration system with strict separation between project understanding, planning, specialist work, guarded mutation, testing, verification, and approval.

## Core flow
```text
User Goal
  ↓
Project/Documentation Discovery
  ↓
Project Scanner
  ↓
Project State Classifier
  ↓
Specification Analyzer
  ↓
Current-State Analyzer
  ↓
Gap/Compliance Analysis
  ↓
Context Builder
  ↓
Central Leader
  ↓
Plan / Decomposition
  ↓
Specialist Workers
  ↓
Independent Validation
  ↓
Execution Authorization (internal)
  ↓
Execution Gate
  ↓
Checkpoint
  ↓
Guarded Apply
  ↓
Tests
  ↓
Verification
  ├─ APPROVE
  └─ ROLLBACK → VERIFY
```

## Autonomous operation
The agent is autonomous by default inside the active project workspace. Internal execution authorization is a machine-checked policy decision, not a request for human confirmation on every file or command.

Human approval is reserved for deployments or explicitly configured high-risk actions outside normal project-development authority.

## Project state
Supported states are BUILD, CONTINUE, MAINTAIN, REPAIR, CONFLICT, and UNKNOWN.

UNKNOWN and unresolved CONFLICT are safety stops.

Confirmed failure evidence takes precedence over maintenance/continuation signals. Tests, build, or syntax failure means REPAIR.

## Leadership
Primary:
- Provider: OpenRouter
- Model: `nvidia/nemotron-3-ultra-550b-a55b:free`

Failover:
- Provider: OpenRouter
- Model: `nvidia/nemotron-3-super-120b-a12b:free`

Leadership is a pool of N connections. The implementation must not encode a fixed account count.

## Workers
Current conceptual roles:
- coder
- debugger
- tester
- architect
- reviewer
- standby

Each role owns a configurable pool. Pool size is configuration, not architecture.

## Identity
Connections use stable IDs such as `OR-01` and `GROQ-01`. IDs are identifiers only; routing must not assume a fixed maximum ID.

## Resource authority
Runtime access is split into three distinct domains:

1. **Workspace authority** — active project files and normal mutation targets.
2. **Tool authority** — explicitly approved development executables, which may reside outside the workspace.
3. **External resource authority** — explicitly declared external files/directories with bounded access mode (`read`, `write`, or `read_write`).

A helper such as `C:\Python312\python.exe` is a tool, not a gateway to the rest of `C:\`. External design/assets folders on another path or drive require explicit resource authorization.

## Execution authority
The model proposes. The local agent validates. Independent validation establishes evidence. Internal execution authorization promotes a validated task to the existing execution gate. The gate controls mutation.

Required mutation path:
1. proposal validation
2. independent validation
3. internal execution authorization
4. checkpoint
5. guarded apply
6. tests
7. verification
8. approve or rollback

## Worker execution boundary
A worker process must not bypass the terminal execution policy.

The standard process path is:

```text
WorkerExecutionBoundary
        ↓
TerminalExecutor
        ↓
TerminalPolicy
        ↓
GitSafetyPolicy (for Git commands)
        ↓
ProcessSandbox
        ↓
Execution Gate
```

`WorkerExecutionBoundary` may accept an explicitly injected executor adapter for tests or tightly controlled integration adapters. It must not silently fall back to raw `subprocess` execution in its normal production path.

## Git safety boundary
Git access through the terminal is repository-inspection only. `GitSafetyPolicy` accepts a narrow set of read-only commands (`status`, `diff`, `log`, `show`, `branch`, `rev-parse`, `ls-files`) and rejects repository/history mutations and authority-expanding operations such as `commit`, `push`, `pull`, `fetch`, `reset`, `clean`, `checkout`, `switch`, `restore`, `merge`, and `rebase`.

Git repository-scope overrides and configuration injection are also rejected. Git path arguments are stricter than generic terminal path handling and must remain workspace-relative where accepted.

Repository mutation uses the separate task-scoped mutation/control plane below; terminal Git access must not silently become that authority.

## Task-scoped Git mutation control plane

`GitMutationExecutor` is the only explicit repository-mutation facade introduced for local autonomous development. It is deliberately separate from the generic terminal path.

```text
ValidationVerdict (passed=true)
        +
Isolated checkpoint attestation
        +
Exact FileChange target set/content
        ↓
ExecutionAuthorizationBoundary
        ↓
GitMutationExecutor
        ↓
GitMutationPolicy
        ↓
ProcessSandbox
        ↓
Git add -- <exact targets>
        ↓
verify staged set == approved set
        ↓
verify current content == validated FileChange.new_text
        ↓
Git commit -m <bounded single-line message>
        ↓
verify HEAD + clean index/worktree + exact committed set
        ↓
verified mutation result
```

The control plane permits only local `stage` and `commit` operations. It does not expose push, pull, fetch, reset, clean, checkout, switch, restore, merge, rebase, cherry-pick, stash, tag, remote, worktree, configuration injection, history amendment, or hook bypass flags.

A workspace-specific mutation lock is acquired before final mutable target validation. Preflight then verifies no pre-existing staged state, no unrelated working-tree changes, and a stable repository `HEAD`. While the lock remains held, target existence/type, symlink/junction containment, UTF-8 decoding, and exact `FileChange.new_text` equality are revalidated immediately before staging.

Mutation success requires exact staged targets, a changed and internally consistent `HEAD`, a clean post-commit index/worktree, and exact committed target-set verification. The implementation accepts 40-character SHA-1 and 64-character SHA-256 Git object IDs and rejects malformed or inconsistent identity evidence.

Credential-like commit messages are rejected by the centralized secret-redaction classifier before they can enter repository history. Mutation failure preserves staged evidence and never performs blind destructive cleanup.

## Process containment
The optional process sandbox adds explicit tool-path validation, shell-free execution, process-group/session isolation, timeout and output bounds, and child-environment minimization.

These controls are stronger than a raw subprocess launch, but they are not an OS-level filesystem sandbox. A child process can still programmatically open unmanaged paths unless the host provides stronger OS enforcement.

`strict_os_required` therefore fails closed until a validated platform-native filesystem/process sandbox backend exists.

## Expansion invariant
The architecture is N-driven.

Examples:
`11 → 21` leadership, `4 → 10` coder, or any other pool expansion must be resource/configuration expansion, not an architecture rewrite.

## Professional desktop UI / Control Center

The production product surface is a professional Windows desktop **Control Center**. PowerShell, Python entry points, and other command-line interfaces are development, diagnostics, and advanced-operator interfaces; they are not the primary end-user operating surface.

The UI is a thin application boundary over the existing Core and must never become a second execution authority or a second source of truth.

```text
Professional Desktop UI / Control Center
              ↓
      Application/UI Service Boundary
              ↓
            AI-Agent Core
              ↓
 Leader / Workers / Validation / Authorization
              ↓
 Execution Gate / Sandbox / Git Mutation Control Plane
```

The UI must expose, at minimum:

- Dashboard with active project, project state, run phase, leader/failover status, worker-pool availability, current task, validation status, tests, Git state, safety stops, and recent runs.
- Written natural-language chat with the Central Leader, including interpreted objective, plan, progress, evidence, and completion result.
- Project/workspace management with bounded resource authorization, project classification, repository/branch identity, project health, and detected specifications.
- Connections & Pools management for adding/importing, rotating, enabling/disabling, health-checking, and reviewing provider connections without rendering raw secrets.
- Leader/worker fleet state showing role, connection ID, provider/model, lease/runtime health, workload, and recent result.
- Canonical task/run timeline covering discovery through planning, worker execution, independent validation, authorization, execution gate, tests, verification, and APPROVE/SAFE_STOP/ROLLBACK outcomes.
- Evidence/activity views with redacted execution, validation, checkpoint, Git mutation, test, security, and failover evidence.
- Git/Changes inspection with exact validated target set, mutation/checkpoint state, and exact committed-target verification, without unrestricted Git controls.
- Tests & Verification with compile, targeted, regression, smoke/integration, security, and Windows acceptance evidence.
- Safety & Policy center explaining UNKNOWN/CONFLICT stops, resource authorization, sandbox mode, redaction, mutation locks, and rejected operations.
- Settings/Diagnostics with non-secret runtime/configuration information and safe redacted diagnostic export.

The detailed functional, security, UX, and Windows acceptance requirements are authoritative in `PRODUCT_UI_SPEC.md`.

The UI must use structured application intents and typed request/response contracts. It must not execute arbitrary shell strings, bypass Core validation/authorization, invent routing policy, or expose unrestricted filesystem/Git/remote authority.

## Invariants
1. No secret values enter Git.
2. No routing logic depends on a fixed maximum connection ID.
3. No worker pool size is structurally hardcoded.
4. UNKNOWN/CONFLICT cannot auto-execute.
5. Confirmed breakage becomes REPAIR.
6. Model output is untrusted input.
7. Filesystem mutation is guarded.
8. Rollback is independently verified.
9. Local tests determine executable reality.
10. Expansion preserves the same interfaces and rules.
11. No worker receives implicit authority over unrelated filesystem data.
12. External resources require explicit bounded authorization.
13. Normal development remains autonomous; human confirmation is exceptional rather than per-operation.
14. Standard worker process execution crosses the TerminalExecutor and TerminalPolicy boundaries before ProcessSandbox launch.
15. Git terminal access cannot grant repository mutation authority; mutating Git operations require a separate explicit control plane.
16. Git mutation control is task-scoped and consumes independent-validation plus internal authorization evidence.
17. Git mutation must refuse unrelated worktree/index changes and verify exact committed targets before success.
18. Git mutation failure must preserve evidence and must not trigger blind destructive cleanup.
19. Git mutation cannot commit file content that differs from the validated `FileChange.new_text`.
20. Credential-like commit messages are rejected before entering repository history.
21. Final target/content validation occurs while the workspace mutation lock is held immediately before staging.
22. Successful mutation must prove a stable pre-mutation HEAD and a distinct post-mutation HEAD that matches the verified commit object.
23. The primary end-user operating surface is the professional desktop Control Center described by `PRODUCT_UI_SPEC.md`; command-line interfaces remain secondary operational tools.
24. UI actions must cross the same Core authority boundaries as non-UI operation; the UI cannot create a parallel execution or mutation path.
25. UI-visible credentials, diagnostics, activity, and errors must cross centralized redaction before becoming observable or persistent.
26. GUI completion requires real Windows end-to-end acceptance; a mockup or static dashboard is not sufficient evidence.
