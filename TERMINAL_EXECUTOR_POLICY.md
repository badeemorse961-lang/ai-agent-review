# Terminal Executor Policy

## Purpose

The terminal is an execution boundary, not a free-form shell. Commands must pass an explicit policy check before they reach the process sandbox.

## Boundary

```text
Model / Worker command proposal
          ↓
TerminalPolicy
          ↓
Resource / Process Sandbox
          ↓
Execution Gate
```

`TerminalPolicy` decides whether the command shape is allowed. `ProcessSandbox` remains responsible for tool-path authority, workspace/resource validation, process-group containment, environment minimization, timeout, and output bounds. The Execution Gate remains the mutation authority.

## Default command policy

The current explicit development policy permits:

- `python` and `pytest`, while rejecting inline `-c` and `-m` launch forms;
- `git` only when a caller supplies a policy that explicitly enables selected read/local-state subcommands.

Unknown executables are rejected.

Shell wrappers and shell operators such as `cmd`, PowerShell, Bash, `&&`, `||`, `;`, `|`, redirection, and their common aliases are rejected at the terminal-policy boundary.

## Arguments

Every command has a bounded argument count. Command-specific policies may impose a lower limit.

Path-like arguments are checked independently from executable allowlisting. A path outside the active workspace requires an explicit readable external-resource declaration. Tool location alone never grants data authority.

## Security properties

The terminal policy does not rely on quoting or shell escaping for safety because shell execution remains disabled downstream. It rejects dangerous command shapes before process launch and preserves the distinction between:

- executable authority;
- workspace authority;
- external-resource authority.

## Non-goals

This policy does not claim OS-level filesystem isolation. The existing `strict_os_required` behavior remains fail-closed until a validated native sandbox backend exists.

This policy also does not replace the existing Execution Gate, checkpointing, tests, independent validation, or rollback verification.
