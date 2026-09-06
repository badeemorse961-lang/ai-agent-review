# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged commit:

`9a4f08207dfce361c7ec27e6b8150f2638b24090`

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
- dedicated GitSafetyPolicy boundary for terminal Git access;
- inspection-only Git terminal capability;
- rejection of repository/history mutation and repository/configuration scope overrides;
- Git path traversal protection within the active workspace;
- centralized secret redaction for observable and persisted runtime output;
- provider error redaction before health-state persistence;
- secret-bearing ambient environment exclusion from sandboxed children;
- explicit `AGENT_*` environment values registered for invocation-scoped redaction;
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
TerminalExecutor → TerminalPolicy
                    ↓
             GitSafetyPolicy (Git)
                    ↓
              ProcessSandbox
                    ↓
             SecretRedactor
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
- descendant termination on timeout where the host platform supports the implemented process-tree mechanism;
- secret-redaction of captured stdout/stderr before the result becomes observable or persistent.

## Terminal execution policy

`TerminalPolicy` provides an explicit command-shape boundary before process launch:

- unknown executables are rejected;
- command argument counts are bounded;
- shell wrappers and shell operators are rejected;
- inline `-c` and `-m` launch forms are rejected for Python/Pytest;
- Git commands are delegated to the dedicated GitSafetyPolicy;
- path-like command arguments outside the workspace require explicit readable external-resource authority for generic terminal commands.

`TerminalExecutor` is the standard composition point between worker execution and process/resource enforcement. It does not replace the Execution Gate.

## Git safety boundary

Terminal Git access is intentionally inspection-only.

Allowed Git operations are narrowly scoped to repository inspection such as:

```text
status
diff
log
show
branch (inspection)
rev-parse (identity queries)
ls-files
```

Repository/history mutations and authority-expanding operations are rejected, including:

```text
add / commit / push / pull / fetch
reset / clean / checkout / switch / restore
merge / rebase / cherry-pick / stash
config / remote / worktree / submodule / init / tag
```

Git repository/configuration scope overrides such as `-C`, `--git-dir`, `--work-tree`, and config injection are rejected.

Accepted Git path arguments must remain workspace-relative; absolute paths and traversal that resolves outside the active workspace are rejected.

Repository mutation remains the responsibility of a separate future task-scoped control plane with explicit checkpoint and verification semantics. Terminal Git access must not silently become repository mutation authority.

## Secret and log redaction boundary

Raw credentials must never become logs, diagnostics, process results, or persisted runtime state.

`secret_redaction.py` provides the centralized sanitization layer. It combines:

- exact-value replacement for explicitly supplied runtime secrets;
- pattern detection for common bearer credentials and provider-shaped keys;
- redaction of secret-like assignments and query parameters;
- recursive redaction for mapping/list values used by structured diagnostics.

`ProcessSandbox` sanitizes child stdout/stderr before creating `ProcessResult`. Approved `AGENT_*` values supplied for an invocation are registered as exact secrets for that redactor. Ambient variables whose names indicate keys, tokens, secrets, passwords, or authentication are excluded from the child environment by default.

`ExecutionGate` sanitizes pytest stdout/stderr before storing test results in runtime state or returning them. Provider health-check error details are sanitized before being persisted to health JSON. Raw exception text used by the synthetic gate diagnostics crosses the redaction boundary before printing.

Redaction is a backstop, not a replacement for authorization or environment hygiene. Secrets remain local-only and credentials should remain outside child environments and unmanaged resources whenever possible.

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

The worker terminal integration, Git safety, and secret-redaction changes were locally validated on Windows after their complete grouped implementations.

Worker terminal integration head before merge:

`15cf9e537b9e293f85b54e0db8919419f698da91`

Git safety head before merge:

`ae60ed841c62299d87b3d46b0e48f6493721df3c`

Log-redaction head before merge:

`7a6ff2c81e28fda3e444c5e91ca0e4573092992a`

Validated results for the Git safety milestone:

```text
python -m compileall -q .                         PASS
7 Git safety tests                                PASS
10 terminal policy/executor tests                 PASS
125 full-suite tests                              PASS
```

Validated results for the log-redaction milestone:

```text
focused redaction tests                           8 passed
python -m compileall -q .                         PASS
full-suite tests                                  133 passed
working tree                                      CLEAN
```

The final Windows validation occurred after the regex fix that preserves the `Bearer` prefix while redacting the credential value.

No protected local secret files were modified by the promotion path.

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

The Git safety boundary branch was merged to `main` as commit `b44914f12802ff18f36da22a4f0c5b504a91151c`.

The log redaction branch was merged to `main` as commit `9a4f08207dfce361c7ec27e6b8150f2638b24090`.

No local secret files are part of the GitHub promotion path.
