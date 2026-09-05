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

Current registry validation was successful immediately before this handoff.

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

These legacy artifacts are obsolete and are being removed:

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

WorkerRouter v2 synthetic validation passed:

- normal acquisition;
- global uniqueness;
- same-task double-acquire rejection;
- release;
- failure fallback;
- standby;
- persistence.

### Orchestration smoke

Previously passed:

```text
Leader OR-01 / Ultra response
↓
local validation
↓
Worker GROQ-01 / GPT-OSS 120B response
↓
local validation
↓
worker lease released
```

### Project Scanner

Synthetic validation passed.

### Project State Classifier

Version 4 passed 11/11 synthetic cases, including BUILD, CONTINUE, MAINTAIN, REPAIR, CONFLICT, UNKNOWN, README-only BUILD, syntax REPAIR, build-failure REPAIR, REPAIR autostart, and UNKNOWN/CONFLICT autostart prevention.

### Expansion readiness

Dynamic synthetic readiness was validated for N values including:

```text
1, 2, 3, 4, 5, 10, 11, 15, 21, 31, 50, 100
```

Leader primary/failover dynamic tests also passed for 5, 11, 21, and 31.

## 16. GitHub ↔ Local Operating Model

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

## 17. Protected Local State

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

## 18. Local Change Rules

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

## 19. Conflict / Overwrite Rules

Before syncing or replacing repository-controlled files:

- inspect `git status`;
- detect uncommitted local changes;
- never silently overwrite intentional local work;
- preserve local-only secrets and machine state;
- stop on ambiguous conflicts.

`.gitignore` is not a security boundary by itself.

## 20. Testing Policy

A commit is not an operational proof.

Minimum expectations depend on change scope.

For a narrow change:

```text
targeted validation
```

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

## 21. Failure Handling

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

Distinguish:

- implementation defects;
- test defects;
- environment failures;
- dependency failures;
- architectural conflicts;
- stale assumptions.

## 22. Rollback Policy

A rollback is verified only when both mutation restoration and independent post-rollback validation succeed.

```text
rollback performed
        +
post-rollback validation
        =
verified rollback
```

## 23. Current Repository Baseline

Known architecture/rules documents already established in the repository include:

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

## 24. Current Working Checkpoint

At the time this handoff was authored, the local development session had reached this state:

```text
M  .gitignore
D  discover_leader_models.py
D  leader_capabilities.json
D  leader_profiles.json
D  worker_profiles.json
```

Interpretation:

- `.gitignore` was updated to ignore generated profiles;
- leader and worker profile JSON files were removed from Git tracking;
- legacy leader discovery artifacts were staged for deletion;
- registry validation was green;
- registry unit tests were green;
- cached diff checking was clean.

The local working tree therefore contained intentional in-progress cleanup that had **not yet been committed** at the moment of handoff.

The repository revision containing this document may be slightly behind that local checkpoint until the local cleanup is committed and pushed. Always verify with Git before assuming exact parity.

## 25. Exact Next Architectural Milestone

The next major implementation milestone is:

```text
Refactor leader_router.py
and worker_router.py
```

to consume the authoritative registry directly:

```text
config/registry.json
        ↓
config_registry.py
        ↓
LeaderRouter / WorkerRouter
```

Do NOT solve the migration by regenerating profile JSON files.

### Leader Router requirements

The router must derive from the registry:

- provider;
- primary model;
- failover model;
- primary pool;
- failover pool.

It must preserve working semantics for:

- external health;
- runtime failures;
- leases;
- persistence;
- failover;
- SAFE STOP.

### Worker Router requirements

The router must derive from the registry:

- provider;
- model;
- role pools;
- configured worker identities.

It must preserve:

- global uniqueness;
- same-task protection;
- role exhaustion behavior;
- standby behavior;
- health integration;
- runtime persistence.

## 26. Leader Failover Duplication

`leader_failover.py` is an older independent leader-failover implementation.

Final architecture should have one authoritative leader routing/failover runtime.

After `LeaderRouter` is fully authoritative, inspect actual callers and either:

- convert `leader_failover.py` into a thin compatibility adapter; or
- retire/delete it when no legitimate dependency remains.

Do not maintain two independent authorities for leader selection and failover state.

## 27. Other Migration Targets

After router migration, inspect and migrate/retire components that still depend on generated profiles or obsolete configuration paths, especially:

```text
leader_profiles.py
worker_profiles.py
leader_health_check.py
orchestration_smoke_test.py
```

Do not delete a file solely because it looks old. First prove that it has no required dependency and replace any legitimate test/tool functionality elsewhere.

## 28. Connection Manager Hardening

`connection_manager.py` still contains legacy repository-relative secret-file behavior.

Final production design should use a local external secret locator rather than treating repository-relative paths as the permanent secret architecture.

Also fix the identity model so key rotation preserves stable connection IDs. Do not derive account identity solely from secret-file line number.

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
connections.json
```

### Phase B — Verify

Inspect:

```text
git status
git branch
git log --oneline -n 10
```

Then inspect the relevant source files for the current task.

### Phase C — Compare

Compare the handoff checkpoint against actual files, Git history, and tests.

Never assume the handoff is newer than the repository.

If the repository is newer than the handoff, trust the newer verified repository state and then update this document.

If the handoff describes changes that are not in the repository, determine whether they exist as intentional local work before touching them.

### Phase D — Continue

Find the first unfinished milestone.

Do not restart completed work.

Do not redesign validated components without evidence.

Do not repeat old architecture decisions unless new evidence invalidates them.

Continue from the exact next step recorded here.

## 31. Decision Checklist Before Any Code Change

Before editing, confirm:

```text
What requirement justifies this change?
What is the authoritative source?
What is the actual current state?
Which files are in scope?
Which files must not be touched?
What existing tests must remain green?
Is there already a validated component solving part of this?
Can the change be smaller?
What is the rollback path?
```

If these cannot be answered safely, stop and gather evidence.

## 32. Architecture Invariants

The following invariants are mandatory:

1. No secret values enter Git.
2. No routing logic depends on a fixed maximum connection ID.
3. No worker pool size is structurally hardcoded.
4. UNKNOWN cannot auto-execute.
5. Unresolved CONFLICT cannot auto-execute.
6. Confirmed breakage becomes REPAIR.
7. Model output is untrusted input.
8. Filesystem mutation is guarded.
9. Rollback is independently verified.
10. Local executable evidence determines operational reality.
11. Static routing configuration has one authoritative source.
12. Runtime health is separate from static configuration.
13. Pool expansion preserves interfaces and rules.
14. Duplicated runtime authority is eliminated.
15. Ambiguity causes evidence gathering or safe stop, not invented decisions.

## 33. Final Mission Reminder

The end state is:

```text
A controlled autonomous software-engineering system
that understands project state,
plans work,
delegates specialist work,
validates model proposals,
executes through guarded mechanisms,
tests changes,
verifies reality,
rolls back safely,
preserves project memory,
and continues across AI sessions without losing context.
```

The repository is the durable memory.

This file is the continuity protocol.

Actual files, tests, and authoritative specifications remain the final authority.
