# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged commit:

`c02ac89885f5cc223ebdb19700c760da03212708`

This baseline includes:

- registry-driven leader/worker routing;
- runtime connection resilience and lease protection;
- project-understanding pipeline;
- context builder;
- central leader boundary;
- plan/decomposition;
- worker dispatch boundary;
- worker execution boundary;
- independent validation;
- autonomous internal execution authorization;
- existing Execution Gate for checkpoint → apply → tests → verification → approve/rollback.

## Autonomous execution contract

The normal development path is autonomous. Human approval is not required for each file or command.

```text
User Goal
  ↓
Discovery / Understanding
  ↓
Leader / Plan
  ↓
Worker Dispatch
  ↓
Guarded Worker Execution
  ↓
Independent Validation
  ↓
Autonomous Internal Execution Authorization
  ↓
Execution Gate
      Checkpoint → Apply → Tests → Verification
      PASS → APPROVE
      FAIL → ROLLBACK → VERIFY
```

Internal authorization is a machine-checked policy boundary. It is not a human approval prompt.

## Current hardening milestone

Feature branch:

`agent/resource-and-process-boundary`

Purpose:

Add the missing distinction between project workspace authority, tool execution authority, and external resource authority, and add a stronger process-launch boundary without falsely claiming complete OS filesystem isolation.

## Resource authority

`WorkspaceResourcePolicy` establishes three explicit domains:

1. active project workspace;
2. explicitly allowlisted development tool executables, which may reside outside the workspace;
3. explicitly declared external paths with access mode `read`, `write`, or `read_write`.

A helper executable located on `C:\` is therefore usable as a tool without granting the worker arbitrary access to the rest of `C:\`.

An external design/assets directory on another path or drive requires an explicit bounded resource declaration.

## Process containment

`ProcessSandbox` adds:

- explicit absolute tool-path allowlisting;
- explicit workspace `cwd`;
- argument-array execution;
- `shell=False`;
- rejection of shell wrappers and inline interpreter/module launchers;
- new process group/session;
- bounded timeout;
- bounded stdout/stderr;
- minimized child environment with secret-bearing variables excluded by default.

The sandbox also checks declared workspace targets and declared external reads/writes through `WorkspaceResourcePolicy` before launch.

## OS isolation truthfulness

Portable process containment and path validation are not equivalent to a true OS-level filesystem sandbox.

A child process can still programmatically open unmanaged paths unless the host provides stronger OS enforcement.

Therefore:

`strict_os_required`

must fail closed until a validated platform-native filesystem/process sandbox backend exists.

No repository documentation should claim that `workspace_guarded` provides complete OS-level filesystem isolation.

## Protected local state

These files remain local-only and protected from synchronization cleanup:

```text
groq_keys.txt
openrouter_keys.txt
groq_keys.backup.txt
openrouter_keys.backup.txt
```

Other protected local state includes `.env`, machine credentials, local runtime state, local model stores/caches, and preserved profile backups.

Never use destructive repository synchronization that can erase protected local state, including blind `git clean -fd` or `git reset --hard`.

## Required test gate for this milestone

The feature branch must be locally validated only after the complete grouped change set is present.

Required checks:

```text
python -m compileall -q .
python -m pytest -q test_sandbox_policy.py
python -m pytest -q test_process_sandbox.py
python -m pytest -q test_worker_execution_process_sandbox.py
python -m pytest -q
```

The full suite must remain green before promotion.

## Promotion sequence

```text
complete grouped implementation
    ↓
local compile + focused tests + full suite
    ↓
diff review
    ↓
security / secret-boundary review
    ↓
merge to main
```

No local secret files are part of the GitHub promotion path.
