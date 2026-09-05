# AI-Agent Persistent Handoff & Continuation Protocol

> This file is the persistent continuity record for any AI model or coding agent that continues work on this repository.
> It exists so that a new session does not require the human owner to re-explain the project, architecture, rules, history, or current checkpoint.
>
> **Important:** this document is a briefing and memory layer. It never overrides actual repository state, executable tests, or authoritative specifications.

## 1. Mission

Build a professional autonomous AI software-engineering agent.

The system must be able to:

1. understand a software project and its documentation;
2. classify the actual project state;
3. derive requirements and gaps;
4. build sufficient context;
5. use a central leader to plan and decompose work;
6. delegate work to specialized workers;
7. validate model output locally;
8. mutate files only through guarded execution;
9. run tests;
10. independently verify results;
11. approve or rollback changes;
12. preserve architectural memory and continue across AI sessions;
13. stop safely when evidence is insufficient or risk is too high.

The goal is **not** merely an AI that edits files. The goal is a controlled autonomous software-engineering system whose decisions are grounded in project evidence.

## 2. Fundamental Authority Model

The model is a proposal/reasoning engine, not unrestricted execution authority.

Use this truth model:

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

Never:

- invent requirements;
- invent missing behavior;
- perform unrelated refactors;
- modify unrelated files;
- broaden scope without evidence;
- replace a validated architecture only because another design looks attractive;
- remove safety controls to make tests pass.

Prefer the smallest justified change.

## 6. Gap / Compliance Principle

Completion percentage is UI information only. It is not project truth.

```text
What should exist
      VS
What actually exists
      ↓
Gap / Compliance
```

## 7. Leadership

Provider: **OpenRouter**

Primary model:
`nvidia/nemotron-3-ultra-550b-a55b:free`

Failover model:
`nvidia/nemotron-3-super-120b-a12b:free`

Current leadership identities:
`OR-01` through `OR-11`

The implementation is N-driven. The number 11 is configuration, not architecture. The routing implementation must not contain a fixed maximum account count.

Primary and failover currently use the same OpenRouter account identity pool; the tier/model changes, not the account identity namespace.

## 8. Workers

Provider: **Groq**

Model:
`openai/gpt-oss-120b`

Current conceptual roles:

- coder
- debugger
- tester
- architect
- reviewer
- standby

Current configured allocation:

```text
coder     → GROQ-01..GROQ-04
debugger  → GROQ-05..GROQ-07
tester    → GROQ-08..GROQ-09
architect → GROQ-10..GROQ-11
reviewer  → GROQ-12..GROQ-14
standby   → GROQ-15
```

These counts are configuration values, not structural limits.

Worker routing must derive pool membership from authoritative configuration and must not depend on a fixed maximum ID.

## 9. Stable Connection Identity

Connection IDs such as `OR-01` and `GROQ-01` are stable identifiers.

IDs are identifiers only. They are not collection indexes and must not be treated as a fixed capacity.

Future expansion such as:

```text
11 → 21 → 31 → 50 → N
```

must be configuration expansion, not routing-architecture rewrite.

A future secret/key rotation mechanism must preserve stable connection identity. Do not make line position in a secrets file the identity of an account.

## 10. Authoritative Configuration

The intended single source of static routing configuration is:

```text
config/registry.json
```

The validator/loader is:

```text
config_registry.py
```

The registry defines provider/model/pool/role configuration.

Do not create a second authoritative configuration through generated profile files or duplicated hardcoded constants.

Current registry validation is successful.

Expected current counts:

```text
Leader provider  : openrouter
Primary accounts : 11
Failover accounts: 11
Worker provider  : groq
Worker roles     : 6
Worker accounts  : 15
Result           : VALID
```

## 11. Generated Profiles

These are derived artifacts, not authorities:

```text
leader_profiles.json
worker_profiles.json
```

They have been removed from Git tracking and must not be restored as routing configuration sources.

Any component that still requires these files should be migrated to the registry or explicitly classified as obsolete compatibility tooling.

## 12. Legacy Leader Discovery

These legacy artifacts are obsolete and have been removed:

```text
discover_leader_models.py
leader_capabilities.json
```

Do not restore them unless actual dependency evidence establishes a new requirement.

## 13. Execution Authority

Model output is untrusted input.

Required mutation path:

```text
Model Proposal
      ↓
Local Validation
      ↓
Execution Gate
      ↓
Checkpoint
      ↓
Guarded Apply
      ↓
Tests
      ↓
Independent Verification
      ↓
Approve / Rollback
```

The Execution Gate must continue to enforce workspace/path safety, mutation validation, checkpointing, test execution, rollback, and rollback verification.

## 14. Proven Execution-Gate Tests

Previously validated scenarios:

```text
TEST1 valid proposal
→ APPROVED

TEST2 invalid proposal
→ REJECTED

TEST3 path escape
→ REJECTED

TEST4 failing test
→ ROLLED_BACK
→ rollback = true
→ post-rollback tests = PASS
→ VERIFIED_AFTER_ROLLBACK

TEST5 workspace isolation
→ PASS
```

Known future hardening areas:

- terminal executor policy/allowlist;
- active workspace enforcement;
- Git safety;
- log redaction.

Do not weaken the existing safety model while improving these areas.

## 15. Proven Routing / Integration Tests

### Leader failover

Model-aware synthetic failover passed across the current leadership pool:

```text
Ultra OR-01 → OR-11
Super OR-01 → OR-11
then SAFE_STOP
```

An earlier bug caused by shadowing the failover method was fixed.

### Worker Router

Registry-driven synthetic validation passed:

- normal acquisition;
- global uniqueness;
- same-task double-acquire rejection;
- release;
- failure fallback;
- standby;
- persistence.

### Orchestration smoke

The smoke test is registry/router driven and uses run-unique task IDs to avoid collisions with persisted state from prior interrupted runs.

Latest local validation completed twice consecutively without clearing runtime state:

```text
Run 1 → PASS
Run 2 → PASS
```

The leader path successfully exercised runtime failover on one of the observed runs (2 attempts) and succeeded after validation.

### Project Scanner

Synthetic validation passed.

### Project State Classifier

Version 4 passed 11/11 synthetic cases, including BUILD, CONTINUE, MAINTAIN, REPAIR, CONFLICT, UNKNOWN, README-only BUILD, syntax REPAIR, build-failure REPAIR, REPAIR autostart, and UNKNOWN/CONFLICT autostart prevention.

### Expansion readiness

Expansion readiness v2 distinguishes true structural fixed-size assumptions from legitimate CLI/test/self-audit constructs.

Parameterized readiness passed for:

```text
1, 2, 3, 4, 5, 10, 11, 15, 21, 31, 100
```

Dynamic primary/failover simulations passed for:

```text
5, 11, 21, 31
```

The audit itself passes. Any remaining MEDIUM findings are runtime result metadata such as an observed attempt count and do not represent pool structure.

## 16. Regression Repair Discovered During Migration

The full regression suite exposed a pre-existing calculator defect. It was repaired minimally so that:

```text
add(a, b)      → a + b
multiply(a,b)  → a * b
divide(a, b)   → a / b
```

The test source encoding was also normalized to remove a UTF-8 BOM that interfered with audit parsing.

The repair is covered by the passing regression suite.

## 17. GitHub ↔ Local Operating Model

The repository is the shared durable project state and cross-session memory.

Repository:
`badeemorse961-lang/ai-agent-review`

Local working directory:
`D:\AI-Agent\Sandbox\agent-test`

Normal controlled synchronization is:

```text
Repository revision
      ↓
fetch / pull
      ↓
inspect
      ↓
preserve intentional local state
      ↓
local implementation / validation
      ↓
tests
      ↓
commit
      ↓
push
```

The repository should be the transport medium between AI sessions.

A human should not be required to copy architectural context from one chat to another when that context can be stored in the repository.

## 18. Protected Local State

Never commit secrets or sensitive machine state.

Current local secret files include:

```text
groq_keys.txt
openrouter_keys.txt
groq_keys.backup.txt
openrouter_keys.backup.txt
```

Raw keys must never enter source code, JSON configuration, Git history, logs, test output, or this document.

Repository metadata may contain connection IDs and fingerprints, but not raw credentials.

Local generated profile copies remain preserved outside the repository at the protected local backup location created during branch synchronization. They must not be deleted merely because they are absent from Git.

## 19. Local Change Rules

For code changes:

1. inspect the complete current file;
2. inspect all relevant callers/dependencies;
3. identify the authoritative configuration/source;
4. make the smallest justified change;
5. compile/syntax-check;
6. run targeted tests;
7. run affected integration/regression tests;
8. inspect the diff;
9. commit only verified changes;
10. push only after validation.

Do not edit from a partial snippet when the full file is required to preserve behavior.

## 20. Conflict / Overwrite Rules

Before syncing or replacing repository-controlled files:

- inspect `git status`;
- detect uncommitted local changes;
- never silently overwrite intentional local work;
- preserve local-only secrets and machine state;
- stop on ambiguous conflicts.

`.gitignore` is not a security boundary by itself.

## 21. Testing Policy

A commit is not an operational proof.

For an architectural change:

```text
syntax/compile
+
targeted tests
+
regression
+
smoke/integration test
```

Do not push untested routing, execution, security, or synchronization changes.

## 22. Failure Handling

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

Never mask a failure merely to obtain a green test result.

Distinguish implementation defects, test defects, environment failures, dependency failures, architectural conflicts, and stale assumptions.

## 23. Rollback Policy

A rollback is verified only when both mutation restoration and independent post-rollback validation succeed.

```text
rollback performed
        +
post-rollback validation
        =
verified rollback
```

## 24. Current Repository Baseline

Known architecture/rules documents established in the repository include:

```text
ARCHITECTURE.md
PROJECT_RULES.md
CONNECTIONS_AND_POOLS.md
REPOSITORY_LOCAL_BOUNDARY.md
SYNC_RULES.md
SECURITY_AND_EXECUTION_RULES.md
BASELINE_REVIEW_NOTES.md
TASK.md
```

These should be read before making a major architectural change.

The baseline explicitly establishes strict separation of project understanding, planning, specialist work, guarded mutation, testing, verification, and approval.

## 25. Current Verified Checkpoint — 2026-09-05

Working branch:

`agent/registry-router-migration`

Verified head at the last local synchronization:

`13df92082c5b1c0e7795d5034aa44b3e03d0ae8b`

Pull request:

`#1 — Migrate routing to registry and validate N-driven orchestration`

The branch was ahead of `main` with no known divergence at the checkpoint.

### Verified local results

```text
python -m compileall -q .
→ PASS

python -m pytest -q
→ 18 passed

python expansion_readiness_audit.py
→ EXPANSION READINESS AUDIT PASSED ✅

python config_registry.py
→ VALID ✅

python leader_router.py
→ LEADER ROUTER REGISTRY TEST PASSED ✅

python worker_router.py
→ WORKER ROUTER REGISTRY TEST PASSED ✅

python orchestration_smoke_test.py
→ PASSED ✅

python orchestration_smoke_test.py
→ PASSED ✅
```

Observed latest smoke details:

```text
Healthy Ultra leaders : 8
Healthy Super leaders : 10
Configured Groq workers: 15

Leader attempts: 1 on one run, 2 on another
Worker attempts: 1
Leader output validation: PASSED
Worker output validation: PASSED
Project files sent: NO
```

The leader-attempt variation is consistent with runtime failover across eligible connections.

### Expansion audit note

The audit returns `PASS` while allowing informational MEDIUM findings for runtime result metadata such as `$.leader.attempts = 1`. These are execution observations, not routing configuration or fixed pool capacity.

## 26. Promotion Status

The migration has been opened as pull request `#1` for final repository review.

The local verification gate is green, but the migration must not be merged merely because tests pass.

Required final sequence:

```text
local verified
    ↓
complete diff review
    ↓
dependency / architecture review
    ↓
security / secret-boundary review
    ↓
PR review
    ↓
merge to main
```

## 27. Final Diff / Architecture Review Checklist

Inspect for:

- stale generated-profile dependencies;
- hardcoded pool-size assumptions;
- fixed maximum IDs in routing logic;
- duplicated configuration authority;
- runtime-state/schema incompatibilities;
- obsolete legacy artifacts;
- secret-handling regressions;
- unsafe synchronization behavior;
- weakened lease uniqueness or SAFE_STOP semantics;
- regression-test coverage of the new audit and router behavior.

Current executable-evidence conclusion:

- registry-driven leader and worker routing is functioning;
- global worker lease protection remains intact;
- runtime failover works;
- orchestration is repeatable with persisted state;
- expansion readiness synthetic coverage passes;
- full regression passes.

## 28. Connection Manager Hardening — Next Major Milestone

`connection_manager.py` still contains legacy repository-relative secret-file behavior.

Final production design should use a local external secret locator rather than treating repository-relative paths as the permanent secret architecture.

Also fix the identity model so key rotation preserves stable connection IDs. Do not derive account identity solely from secret-file line number.

This work should occur as a separate architectural change after the current migration is promoted, unless final review discovers a blocking dependency.

## 29. Handoff Update Rule

After every major verified milestone, update this document with:

```text
Current checkpoint
What changed
Why it changed
Files affected
Tests run
Test results
Known issues
Next exact step
```

The handoff must describe the **verified** state, not an optimistic intended state.

When updating it, never delete useful historical facts merely to make the document shorter.

## 30. New AI Session Startup Protocol

A new AI model connected to this repository MUST behave as a continuation agent, not as a new-project assistant.

### Phase A — Read

Read:

```text
AI_AGENT_HANDOFF.md
ARCHITECTURE.md
PROJECT_RULES.md
CONNECTIONS_AND_POOLS.md
REPOSITORY_LOCAL_BOUNDARY.md
SYNC_RULES.md
SECURITY_AND_EXECUTION_RULES.md
BASELINE_REVIEW_NOTES.md
TASK.md
config/registry.json
config_registry.py
roles.json
```

Then verify the actual Git branch, working tree, and current test state before making claims.

### Phase B — Verify

Check:

```text
git status

git branch --show-current

git log -1 --oneline
```

Then run only the tests needed to establish current reality for the requested task.

### Phase C — Continue

Continue from verified repository state.

Do not:

- rebuild the project from memory;
- recreate retired profile generators without evidence;
- trust stale generated artifacts;
- overwrite protected local secrets;
- delete intentional local work;
- bypass execution or validation safety rules;
- assume a historical green test proves the current working tree is green.

### Phase D — Update Memory

When a major milestone is verified, update this handoff and the relevant checkpoint documentation so the next AI session can continue without reconstructing the entire history.
