# Security and Execution Rules

## Trust boundary
Model output is untrusted input.

The model may propose plans, edits, commands, diagnoses, or role assignments, but it may not directly mutate the filesystem or execute unrestricted commands.

## Authority model
The runtime separates three distinct authorities:

1. **Workspace authority** — the active project workspace is the default data boundary for project mutation.
2. **Tool authority** — development executables may live outside the workspace (for example Python, Git, or Node), but an executable's location does not grant arbitrary filesystem authority.
3. **External resource authority** — files/directories outside the workspace require an explicit resource declaration with a bounded access mode (`read`, `write`, or `read_write`).

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

## Tool execution
Production worker execution should use the process sandbox layer where available. It enforces:
- explicit absolute tool allowlisting when the sandbox is enabled
- explicit working directory
- argument arrays
- `shell=False`
- rejection of shell wrappers and inline interpreter/module launchers
- process-group/session isolation
- bounded execution time
- bounded output
- minimized/sanitized child environment

## OS-level isolation limitation
`cwd`, path validation, and process-group isolation are **not** equivalent to an OS-level filesystem sandbox. A child process can still programmatically open unmanaged paths unless the host provides stronger OS enforcement.

The `strict_os_required` mode therefore fails closed until a platform-native filesystem/process sandbox backend is installed and validated. The runtime must not claim full filesystem isolation while only the portable workspace-guarded backend is active.

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
Never expose raw API keys, authorization headers, or secret environment variables in logs.

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

## Principle
```text
Strong model
    ≠
unrestricted authority
```
