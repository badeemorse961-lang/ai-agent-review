# Architecture

```text
User Goal
  ↓
Discovery
  ↓
Scanner
  ↓
State Classifier
  ↓
Specification Analyzer
  ↓
Current-State Analyzer
  ↓
Gap / Compliance
  ↓
Context Builder
  ↓
Central Leader
  ↓
Plan / Decomposition
  ↓
Workers
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
  ├─ PASS → APPROVE
  └─ ROLLBACK → VERIFY
```

## Autonomous operation
The agent is autonomous by default inside the active project workspace. Internal execution authorization is a machine-checked policy decision, not a request for human confirmation on every file or command.

Human approval is reserved for deployments or explicitly configured high-risk actions outside normal project-development authority.

## Resource authority
Execution uses three separate authority domains:

- **Workspace:** project files and normal mutation targets.
- **Tools:** approved development executables, which may physically reside outside the workspace.
- **External resources:** explicitly declared external files/directories with a bounded access mode.

A tool path such as `C:\Python312\python.exe` grants executable authority only. It does not grant authority over the rest of `C:\`.

## Project state
Supported states are BUILD, CONTINUE, MAINTAIN, REPAIR, CONFLICT, and UNKNOWN.

## Leadership and workers
Leader and worker pools are configuration-driven. Each role owns a configurable pool. Pool size is configuration, not architecture.

Connections use stable IDs such as `OR-01` and `GROQ-01`. IDs are identifiers only; routing must not assume a fixed maximum ID.

## Execution authority
The model proposes. The local agent validates. Independent validation establishes evidence. Internal execution authorization promotes the validated task to the existing execution gate. The gate controls mutation.

Required mutation path:
1. proposal validation
2. independent validation
3. internal execution authorization
4. checkpoint
5. guarded apply
6. tests
7. verification
8. approve or rollback

## Process containment
The optional process sandbox adds explicit tool-path validation, shell-free execution, process-group/session isolation, timeout and output bounds, and child-environment minimization.

These controls are stronger than a raw `subprocess.run`, but they are not an OS-level filesystem sandbox. The `strict_os_required` mode must fail closed until a validated native sandbox backend exists for the host platform.

## Expansion invariant
The architecture is N-driven.

Examples:
`11 → 21` leadership, `4 → 10` coder, or any other pool expansion must be resource/configuration expansion, not an architecture rewrite.

## Invariants
1. No secret values enter Git.
2. No routing logic depends on a fixed maximum connection ID.
3. No worker receives implicit authority over unrelated filesystem data.
4. External resources require explicit bounded authorization.
5. Normal development remains autonomous; human confirmation is exceptional rather than per-operation.
