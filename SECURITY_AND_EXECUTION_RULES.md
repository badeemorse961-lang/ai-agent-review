# Security and Execution Rules

## Trust boundary
Model output is untrusted input.

The model may propose plans, edits, commands, diagnoses, or role assignments, but it may not directly mutate the filesystem or execute unrestricted commands.

## Authority model
The runtime separates four distinct authorities:

1. **Workspace authority** — the active project workspace is the default data boundary for project mutation.
2. **Tool authority** — development executables may live outside the workspace (for example Python, Git, or Node), but an executable's location does not grant arbitrary filesystem authority.
3. **Repository authority** — access to Git metadata is not equivalent to authority to rewrite repository history or remote state.
4. **External resource authority** — files/directories outside the workspace require an explicit resource declaration with a bounded access mode (`read`, `write`, or `read_write`).

Using a helper executable from `C:\` or another system location is therefore not equivalent to granting the worker access to all of that drive.

## Execution Gate
```text
Proposal
  ↓
Independent validation
  ↓
Internal execution authorization
  ↓
Checkpoint
  ↓
Guarded apply
  ↓
Tests
  ↓
Verification
  ↓
Approve OR Rollback
```

Normal project development does not require human confirmation for each file or command. Human approval is reserved for deployments and explicitly configured high-risk actions outside normal project-development authority.

## Path security
Every filesystem mutation target must resolve inside the explicit active workspace.

Reject:
- path traversal
- absolute paths outside workspace
- symlink/junction escapes
- wrong target type
- undeclared external resources

## External resources
External resources must be explicitly declared before use. Resource declarations are narrow path prefixes plus an access mode.

A read-only declaration cannot be used for writes. `read_write` is required for bidirectional access.

External resources should be used for concrete project needs such as explicitly selected design/assets directories. Unrelated personal data, credentials, unrelated projects, and system locations remain unmanaged and must not be accessed implicitly.

## Terminal execution boundary
Worker process execution must use the policy-first terminal path:

```text
WorkerExecutionBoundary
      ↓
TerminalExecutor
      ↓
TerminalPolicy
      ↓
GitSafetyPolicy (for Git)
      ↓
ProcessSandbox
      ↓
SecretRedactor
```

`TerminalPolicy` rejects unknown executables, dangerous shell wrappers/operators, forbidden inline interpreter launchers, overlong command shapes, and unauthorized path-like arguments before launch.

`GitSafetyPolicy` is a stricter repository-specific boundary. It permits only read-only inspection operations through the terminal and rejects commands that mutate history, working-tree state, refs, remotes, or Git configuration.

A worker boundary with no controlled terminal executor must fail closed rather than silently falling back to raw `subprocess` execution. Explicit test/integration executor adapters remain possible through dependency injection and are not the default production path.

## Git safety boundary
The terminal Git capability is intentionally inspection-only:

```text
Allowed:
  status
  diff
  log
  show
  branch (inspection)
  rev-parse (identity queries)
  ls-files

Rejected:
  add / commit / push / pull / fetch
  reset / clean / checkout / switch / restore
  merge / rebase / cherry-pick / stash
  config / remote / worktree / submodule / init
```

The Git policy also rejects repository/configuration overrides such as `-C`, `--git-dir`, `--work-tree`, Git config injection, executable-path overrides, and unapproved pathspec modes. This prevents a terminal Git command from redirecting authority to a different repository or environment.

Git path arguments are workspace-relative where accepted. External-resource declarations do not expand Git repository authority.

Repository mutation remains the responsibility of a future separate task-scoped control plane that can bind mutation to validated targets, checkpoints, and post-mutation verification.

## Tool execution
Production worker execution should use the terminal executor above the process sandbox. The composed layers enforce:
- explicit absolute tool allowlisting when the sandbox is enabled
- explicit working directory
- argument arrays
- `shell=False`
- rejection of shell wrappers and inline interpreter/module launchers
- process-group/session isolation
- bounded execution time
- bounded output
- minimized/sanitized child environment
- Git repository inspection policy when the Git executable is selected
- secret redaction of stdout/stderr before the result becomes observable or persistent

## Log redaction and secret leakage prevention
Raw credentials must never become logs, diagnostics, process results, or persisted runtime state.

`secret_redaction.py` provides a centralized redaction boundary. It combines exact-value replacement for explicitly supplied secret values with pattern-based detection for common credential forms such as bearer authorization values, Groq keys, OpenRouter keys, generic `sk-*` credentials, and secret-like assignments/query parameters.

`ProcessSandbox` applies the redactor before constructing `ProcessResult`, so callers do not receive raw child-process output. Approved `AGENT_*` environment values are registered as explicit secrets for that invocation. Ambient variables whose names indicate keys, tokens, secrets, passwords, or authentication are excluded from the child environment by default.

`ExecutionGate` redacts test stdout/stderr before storing them in execution state or returning them. Provider health-check errors are redacted before they are persisted to health JSON.

Redaction is a backstop rather than an authorization mechanism. Credentials must remain outside source control and should remain outside child environments and unmanaged resources whenever possible.

## OS-level isolation limitation
`cwd`, path validation, and process-group isolation are **not** equivalent to an OS-level filesystem sandbox. A child process can still programmatically open unmanaged paths unless the host provides stronger OS enforcement.

The `strict_os_required` mode therefore fails closed until a platform-native filesystem/process sandbox is installed and validated. The runtime must not claim full filesystem isolation while only the portable workspace-guarded backend is active.

## Exact change validation
Reject:
- zero old-text matches
- multiple old-text matches
- duplicate target files in one transaction
- invalid encoding
- targets outside workspace

## Checkpoints
Each mutation transaction requires an isolated checkpoint containing enough metadata to restore the prior state.

## Rollback
Rollback is not complete until post-rollback tests/validation pass. If rollback verification fails: `SAFE_STOP`.

## Sensitive output
Never expose raw API keys, authorization headers, secret environment variables, or unredacted provider error details in logs or persisted runtime state. Any captured stdout/stderr must cross the redaction boundary before it is returned or stored.

## SAFE_STOP
Stop rather than guess when:
- specification conflicts are unresolved
- required context is missing
- rollback cannot be verified
- workspace boundaries cannot be enforced
- an external resource is undeclared or has insufficient access
- an approved tool cannot be identified exactly
- a suitable OS-level sandbox is required but unavailable
- suitable model connections are exhausted
- validation cannot prove a change is safe
- a Git command would mutate repository state outside the approved control plane
- a secret-bearing output cannot be confidently redacted

## Principle
```text
Strong model
    ≠
unrestricted authority
```
