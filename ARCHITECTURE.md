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
ProcessSandbox
        ↓
Execution Gate
```

`WorkerExecutionBoundary` may accept an explicitly injected executor adapter for tests or tightly controlled integration adapters. It must not silently fall back to raw `subprocess` execution in its normal production path.

## Process containment
The optional process sandbox adds explicit tool-path validation, shell-free execution, process-group/session isolation, timeout and output bounds, and child-environment minimization.

These controls are stronger than a raw subprocess launch, but they are not an OS-level filesystem sandbox. A child process can still programmatically open unmanaged paths unless the host provides stronger OS enforcement.

`strict_os_required` therefore fails closed until a validated platform-native filesystem/process sandbox backend exists.

## Expansion invariant
The architecture is N-driven.

Examples:
`11 → 21` leadership, `4 → 10` coder, or any other pool expansion must be resource/configuration expansion, not an architecture rewrite.

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
