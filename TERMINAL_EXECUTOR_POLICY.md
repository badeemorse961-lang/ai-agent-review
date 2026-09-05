# Terminal Executor Policy

## Purpose

The terminal is an execution boundary, not a free-form shell. Commands must pass an explicit policy check before they reach the process sandbox.

## Boundary

```text
Model / Worker command proposal
          ↓
TerminalPolicy
          ↓
GitSafetyPolicy (for Git)
          ↓
Resource / Process Sandbox
          ↓
Execution Gate
```

`TerminalPolicy` decides whether the command shape is allowed. `ProcessSandbox` remains responsible for tool-path authority, workspace/resource validation, process-group containment, environment minimization, timeout, and output bounds. The Execution Gate remains the mutation authority.

## Default command policy

The current explicit development policy permits:

- `python` and `pytest`, while rejecting inline `-c` and `-m` launch forms;
- `git` through a dedicated `GitSafetyPolicy` for repository-inspection commands only.

Unknown executables are rejected.

## Git safety boundary

Git is not treated as a generic executable whose subcommand list can be widened by a caller. When Git is enabled in `TerminalPolicy`, every Git command crosses the dedicated `GitSafetyPolicy`.

The terminal boundary currently permits only read-only repository inspection:

```text
status
 diff
 log
 show
 branch
 rev-parse
 ls-files
```

The policy rejects repository/history mutations and other authority-expanding commands, including:

```text
add        commit      push        pull        fetch
reset      clean       checkout    switch      restore
merge      rebase      cherry-pick stash       tag
config     remote      worktree    submodule   init
```

Repository-scope overrides such as `-C`, `--git-dir`, `--work-tree`, Git configuration injection, executable-path overrides, and custom pathspec modes are rejected. Git path arguments must remain workspace-relative when path arguments are accepted.

This is intentional: repository mutation is not silently granted by terminal access. A future mutation capability should be introduced as a separate, task-scoped, policy-checked control plane with explicit checkpoint and verification semantics.

## Arguments

Every command has a bounded argument count. Command-specific policies may impose a lower limit.

Path-like arguments are checked independently from executable allowlisting. A path outside the active workspace requires an explicit readable external-resource declaration. Tool location alone never grants data authority. Git uses the stricter workspace-relative path rule for its accepted path arguments.

## Security properties

The terminal policy does not rely on quoting or shell escaping for safety because shell execution remains disabled downstream. It rejects dangerous command shapes before process launch and preserves the distinction between:

- executable authority;
- workspace authority;
- repository authority;
- external-resource authority.

The Git safety boundary is fail-closed: an unknown or mutating Git operation is rejected before the process sandbox can launch it.

## Non-goals

This policy does not claim OS-level filesystem isolation. The existing `strict_os_required` behavior remains fail-closed until a validated native sandbox backend exists.

This policy also does not replace the existing Execution Gate, checkpointing, tests, independent validation, or rollback verification.
