# AI-Agent Persistent Handoff & Continuation Protocol

> This file is the persistent continuity record for any AI model or coding agent that continues work on this repository.
> It exists so that a new session does not require the human owner to re-explain the project, architecture, rules, history, or current checkpoint.
>
> **Important:** this document is a briefing and memory layer. It never overrides actual repository state, executable tests, or authoritative specifications.

## 1. Mission

Build a professional autonomous AI software-engineering agent whose decisions are grounded in project evidence and whose mutation authority is explicitly controlled.

The system must be able to understand a project, classify state, derive requirements and gaps, build context, plan and decompose work, delegate specialized workers, validate model output, mutate only through guarded boundaries, run tests, independently verify results, approve or rollback safely, preserve architectural memory, and stop safely when evidence is insufficient.

The goal is **not** merely an AI that edits files. The goal is a controlled autonomous software-engineering system with explicit authority separation.

## 2. Fundamental Authority Model

The model is a proposal/reasoning engine, not unrestricted execution authority.

```text
Authoritative Specification
        +
Actual Project State
        +
Executable Evidence
        =
Operational Truth
```

Evidence priority:

1. actual files and current project state;
2. executable tests/build/syntax results;
3. authoritative specifications;
4. recorded architectural decisions;
5. model reasoning.

Model reasoning alone cannot establish implementation reality.

## 3. Target Architecture

The intended flow is:

```text
User Goal
  ↓
Project / Documentation Discovery
  ↓
Project Scanner
  ↓
Project State Classifier
  ↓
Specification Analyzer
  ↓
Current-State Analyzer
  ↓
Gap / Compliance Analysis
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
Internal Execution Authorization
  ↓
Worker Execution Boundary
  ↓
TerminalExecutor → TerminalPolicy
  ↓
ProcessSandbox → SecretRedactor
  ↓
Execution Gate
  ↓
Checkpoint → Guarded Apply → Tests → Verification
  ├─ APPROVE
  └─ ROLLBACK → VERIFY
  ↓
Task-scoped Git mutation control plane when repository mutation is explicitly required
```

Separation of concerns is mandatory: understanding, planning, delegation, execution, validation, verification, and approval must not collapse into one uncontrolled component.

## 4. Project-State Classification

Supported states:

- BUILD — design/specification exists and implementation is absent or minimal.
- CONTINUE — implementation exists but required work remains.
- MAINTAIN — project is substantially complete and stable.
- REPAIR — confirmed test/build/syntax or equivalent breakage exists.
- CONFLICT — authoritative requirements contradict each other and cannot be safely reconciled.
- UNKNOWN — insufficient evidence for a safe autonomous decision.

Confirmed breakage takes precedence over continuation/maintenance signals.

UNKNOWN and unresolved CONFLICT are safety stops.

## 5. No Invented Scope

Never invent requirements, missing behavior, unrelated refactors, unrelated-file changes, broad scope without evidence, or replacements of validated architecture merely because another design looks attractive.

Prefer the smallest justified change.

## 6. Leadership and Workers

Leadership uses an N-driven OpenRouter pool. Worker routing uses registry-defined roles and pools. Connection IDs such as `OR-01` and `GROQ-01` are stable identifiers only and are not fixed capacity limits.

The authoritative static routing configuration is `config/registry.json`, loaded and validated by `config_registry.py`.

Generated profiles such as `leader_profiles.json` and `worker_profiles.json` are derived local artifacts, not routing authorities.

## 7. Execution and Resource Authority

The active workspace is the default filesystem mutation authority. Development tools may be located outside the workspace, but tool location is not filesystem authority. External paths require explicit bounded resource declarations.

The standard worker process path is:

```text
WorkerExecutionBoundary
        ↓
TerminalExecutor
        ↓
TerminalPolicy
        ↓
GitSafetyPolicy for Git inspection
        ↓
ProcessSandbox
        ↓
SecretRedactor
```

Portable process containment must not be described as complete OS filesystem isolation. `strict_os_required` fails closed until a validated native backend exists.

## 8. Git Safety and Mutation Authority

Normal terminal Git access is inspection-only through `GitSafetyPolicy`. Repository mutation is separate.

The task-scoped Git mutation control plane is:

```text
Passed ValidationVerdict
        +
Isolated checkpoint
        +
Exact FileChange targets/content
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
verify staged set
        ↓
verify current content == validated FileChange.new_text
        ↓
Git commit -m <bounded message>
        ↓
verify HEAD + clean index/worktree + exact committed set
```

Only local `stage` and `commit` are exposed by this control plane. No push, pull, fetch, reset, clean, branch switching, merge, rebase, cherry-pick, stash, tag, remote, worktree, configuration injection, amendment, or hook bypass is available.

Every repository mutation is bound to task identity, worker identity, passed independent validation, isolated checkpoint evidence, exact targets, and validated target content. Unrelated staged/worktree changes, content drift, invalid targets, symlink escapes, live/ambiguous mutation locks, or untrustworthy Git evidence are SAFE_STOP conditions.

Commit messages are bounded single-line history and are rejected when the centralized secret-redaction policy classifies them as credential-like material.

Mutation failures preserve evidence and never trigger blind reset/clean/delete synchronization.

## 9. Secret and Log Safety

Raw credentials must never become logs, diagnostics, process results, or persisted runtime state.

The centralized `SecretRedactor` provides exact-value replacement plus pattern detection for common credentials. `ProcessSandbox`, `ExecutionGate`, and provider health persistence cross the redaction boundary before output becomes observable or persistent.

Credential-bearing ambient environment variables are excluded from child processes by default; explicitly approved `AGENT_*` values are registered for invocation-scoped exact redaction.

## 10. GitHub ↔ Local Operating Model

Repository:
`badeemorse961-lang/ai-agent-review`

Local working directory:
`D:\AI-Agent\Sandbox\agent-test`

Normal synchronization is fetch/pull-fast-forward followed by inspection and validation. Do not use blind `git clean -fd` or `git reset --hard`.

Protected local secret files remain local-only:

```text
groq_keys.txt
openrouter_keys.txt
groq_keys.backup.txt
openrouter_keys.backup.txt
```

Local generated profiles and other runtime/machine state must also be preserved when absent from Git.

## 11. Testing Policy

A commit is not an operational proof.

For an architectural change:

```text
syntax/compile
+
targeted tests
+
regression suite
+
smoke/integration validation
+
diff review
+
security-boundary review
```

Do not claim local success without execution evidence.

## 12. Failure Handling

When a test fails:

```text
STOP
  ↓
classify the failure
  ↓
preserve evidence
  ↓
fix the real cause
  ↓
retest
```

Never mask a failure to manufacture a green result.

## 13. Current Verified Baseline

The latest synchronized `main` baseline is the log-redaction milestone plus its checkpoint update. The current engineering milestone is the task-scoped Git mutation control plane in pull request `#17`.

PR `#17` initially exposed two genuine defects during the Windows validation gate:

1. Windows `pathlib` normalized `./file.py` before the policy inspected its parts, so explicit traversal syntax was not rejected.
2. `ProcessSandbox` rejected `-m` universally, which incorrectly blocked the dedicated Git commit command even though `-m` must remain forbidden only for Python/Pytest inline launchers.

These defects were corrected on the feature branch.

Additional hardening now present on the branch includes:

- rejection of credential-like commit messages before Git history is written;
- rejection of post-validation target-content drift when current content differs from `FileChange.new_text`;
- focused regression coverage for both protections;
- hardened Git mutation documentation and architecture rules.

The branch must still pass the real Windows validation gate before merge.

## 14. Required Promotion Sequence

```text
complete grouped implementation
    ↓
Windows compile + focused tests + full suite
    ↓
diff review
    ↓
security / secret-boundary review
    ↓
merge to main
    ↓
update CURRENT_CHECKPOINT.md
```

No local secret file is part of the GitHub promotion path.

## 15. Continuation Rule

Before starting a new milestone, inspect:

```text
CURRENT_CHECKPOINT.md
TASK.md
BASELINE_REVIEW_NOTES.md
ARCHITECTURE.md
PROJECT_RULES.md
SECURITY_AND_EXECUTION_RULES.md
GIT_MUTATION_CONTROL_PLANE.md
```

Then inspect the executable code and tests relevant to the next gap. Prefer substantive engineering gaps over documentation-only cleanup.
