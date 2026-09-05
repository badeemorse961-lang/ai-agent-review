# Security and Execution Rules

## Trust boundary
Model output is untrusted input.

The model may propose plans, edits, commands, diagnoses, or role assignments, but it may not directly mutate the filesystem or execute unrestricted commands.

## Execution Gate
```text
Proposal
  ↓
Independent validation
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

## Path security
Every filesystem target must resolve inside the explicit active workspace.

Reject:
- path traversal
- absolute paths outside workspace
- symlink/junction escapes
- wrong target type

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

## Command execution
Production terminal execution should enforce:
- explicit working directory
- argument arrays where possible
- `shell=False` where possible
- command policy/allowlist
- timeouts
- audited output
- secret redaction

## Sensitive output
Never expose raw API keys, authorization headers, or secret environment variables in logs.

## SAFE_STOP
Stop rather than guess when:
- specification conflicts are unresolved
- required context is missing
- rollback cannot be verified
- workspace boundaries cannot be enforced
- suitable model connections are exhausted
- validation cannot prove a change is safe

## Principle
```text
Strong model
    ≠
unrestricted authority
```
