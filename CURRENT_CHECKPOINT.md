# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged commit:

`07184e7ed8c5516095d8cc6b2b6fad31e24a438a`

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
- terminal command policy and policy-first terminal executor;
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
Terminal Policy
  ↓
Process / Resource Sandbox
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

## Terminal execution policy

`TerminalPolicy` is the command-shape boundary immediately before process execution.

It enforces:

- explicit executable-family allowlisting;
- global and per-command argument bounds;
- command-specific forbidden arguments;
- rejection of shell wrappers/operators;
- rejection of inline Python/Pytest launch forms such as `-c` and `-m`;
- validation of path-like command arguments against workspace or explicitly readable external resources.

`TerminalExecutor` composes this policy with `ProcessSandbox`. Terminal policy does not replace process/resource validation or the Execution Gate.

The default policy permits `python` and `pytest` while keeping inline execution disabled. Git is intentionally not unrestricted by default; callers must provide a narrowed subcommand policy when Git execution is needed.

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

The complete terminal-policy branch was validated on the real Windows development environment:

```text
python -m compileall -q .                 PASS
6 terminal-policy tests                   PASS
3 terminal-executor tests                 PASS
20 prior sandbox/resource tests            PASS
115 full-suite tests                       PASS
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
```

The terminal-policy branch has been merged to `main` as commit `07184e7ed8c5516095d8cc6b2b6fad31e24a438a`.

No local secret files are part of the GitHub promotion path.
