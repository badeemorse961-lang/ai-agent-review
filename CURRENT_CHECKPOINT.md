# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged commit:

`e60b6b70dd899d734f4a7afd1ab03bf45b9cc8df`

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
- workspace/tool/external-resource authority separation;
- process sandbox boundary with explicit tool allowlisting and bounded execution;
- policy-first terminal execution boundary;
- explicit terminal executable/subcommand allowlisting and bounded command shape;
- standard Worker → TerminalExecutor → TerminalPolicy → ProcessSandbox execution path;
- no raw `subprocess` fallback in normal worker production execution;
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
WorkerExecutionBoundary
  ↓
TerminalExecutor → TerminalPolicy → ProcessSandbox
  ↓
Execution Gate
      Checkpoint → Apply → Tests → Verification
      PASS → APPROVE
      FAIL → ROLLBACK → VERIFY
```

Internal authorization is a machine-checked policy boundary. It is not a human approval prompt.

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
- minimized child environment with secret-bearing variables excluded by default;
- explicit validation of command path arguments against workspace/external-resource authority;
- descendant termination on timeout where the host platform supports the implemented process-tree mechanism.

## Terminal execution policy

`TerminalPolicy` provides an explicit command-shape boundary before process launch:

- unknown executables are rejected;
- command argument counts are bounded;
- shell wrappers and shell operators are rejected;
- inline `-c` and `-m` launch forms are rejected for Python/Pytest;
- Git subcommands are allowlisted rather than granting unrestricted Git execution;
- path-like command arguments outside the workspace require explicit readable external-resource authority.

`TerminalExecutor` is the standard composition point between worker execution and process/resource enforcement. It does not replace the Execution Gate.

## Worker execution rule

Normal worker execution must cross the following controlled path:

```text
WorkerExecutionBoundary
        ↓
TerminalExecutor
        ↓
TerminalPolicy
        ↓
ProcessSandbox
```

An explicitly injected executor adapter remains available only for tests or tightly controlled integration adapters. The production default must fail closed rather than silently falling back to raw `subprocess` execution.

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

## Validation record

The worker terminal integration branch was locally validated on Windows after the complete grouped implementation at commit `15cf9e537b9e293f85b54e0db8919419f698da91`:

```text
python -m compileall -q .                         PASS
13 worker-execution tests                          PASS
3 worker-process-sandbox tests                    PASS
9 terminal-policy/executor tests                  PASS
117 full-suite tests                               PASS
```

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
    ↓
update CURRENT_CHECKPOINT.md
```

The worker terminal integration branch was merged to `main` as commit `e60b6b70dd899d734f4a7afd1ab03bf45b9cc8df`.

No local secret files are part of the GitHub promotion path.
