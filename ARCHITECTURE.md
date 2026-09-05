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
Apply
  ↓
Tests
  ↓
Verification
  ├─ APPROVE
  └─ ROLLBACK → VERIFY
```

## Autonomous operation
The agent is autonomous by default inside the active project workspace. Internal execution authorization is a machine-checked policy decision, not a request for human confirmation on every file or command.

Human approval is reserved for deployments or explicitly configured high-risk actions outside the normal project-development authority.

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

## Execution authority
The model proposes. The local agent validates. Internal execution authorization promotes a validated task to the existing execution gate. The gate controls mutation.

Required mutation path:
1. proposal validation
2. independent validation
3. internal execution authorization
4. checkpoint
5. guarded apply
6. tests
7. verification
8. approve or rollback

## Expansion invariant
The architecture is N-driven.

Examples:
`11 → 21` leadership, `4 → 10` coder, or any other pool expansion must be resource/configuration expansion, not an architecture rewrite.

## Review findings
The repository currently contains multiple generations of role-management logic, an older experimental `agent.py`, and fixed-size assumptions in role/profile generation. These must be normalized before the final baseline.

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
