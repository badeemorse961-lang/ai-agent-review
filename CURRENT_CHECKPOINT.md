# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`653b2b842e5f4c734b3390b1baec31c70f6ff3d7`

This squash merge promotes pull request `#19`, which hardens Execution Gate test-process execution by routing gate-owned pytest execution through the established ProcessSandbox boundary without expanding mutation authority.

Previous promoted milestone:

`a5a61d7fcb36efe177c4f779204e4b87b8281c22` — PR #18 transaction hardening.

## Verified architecture

The repository includes registry-driven leader/worker routing, runtime connection resilience, project understanding, context building, central leadership, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized secret/log redaction, a separate task-scoped Git mutation control plane, and a dedicated Execution Gate process boundary.

The normal worker process path remains:

```text
WorkerExecutionBoundary
  ↓
TerminalExecutor
  ↓
TerminalPolicy
  ↓
GitSafetyPolicy for Git inspection
  ↓
ProcessSandbox
  ↓
SecretRedactor
  ↓
Execution Gate
```

Gate-owned test execution is now:

```text
ExecutionGate
  ↓
ExecutionGateProcessRunner
  ↓
WorkspaceResourcePolicy
  ↓
ProcessSandbox
  ↓
pytest
```

The gate runner resolves an absolute pytest executable, allowlists that executable for the active workspace, executes shell-free with process-group containment and bounded timeout/output, and registers only explicit `AGENT_*` environment values for exact redaction. Ambient provider credentials remain excluded.

## Task-scoped Git mutation control plane

The promoted control plane remains:

```text
Passed ValidationVerdict
        +
Isolated checkpoint
        +
Exact FileChange targets/content
        ↓
ExecutionAuthorizationBoundary
        ↓
GitMutationExecutor
        ↓
GitMutationPolicy
        ↓
ProcessSandbox
        ↓
Git add -- <exact targets>
        ↓
verify staged target set
        ↓
verify staged index content == validated FileChange.new_text
        ↓
Git commit -m <bounded single-line message>
        ↓
verify HEAD + clean index/worktree + exact committed target set
```

Only local `stage` and `commit` operations are exposed. Remote mutation, history rewriting, destructive cleanup, branch switching, merge/rebase/cherry-pick/stash, configuration injection, amendment, signing overrides, and hook bypass are not exposed.

Every mutation consumes prior independent-validation and internal authorization evidence. It cannot self-authorize.

## Transaction hardening

The mutation lock is acquired before final mutable target validation. While the lock is held, target type, symlink/junction containment, UTF-8 decoding, and exact current-content equality with validated `FileChange.new_text` are revalidated immediately before staging.

After staging, the executor resolves the Git object format and verifies the exact staged blob object ID for every authorized target against the validated file content. An ambiguous index entry, unsupported object format, or staged-content mismatch stops before commit.

The transaction captures pre-mutation `HEAD`, proves it remains stable through final preflight, and after commit requires a distinct post-commit `HEAD` that matches the independently resolved commit identity used for exact target-set inspection.

Only structurally valid 40-character SHA-1 and 64-character SHA-256 Git object IDs are accepted.

Mutation failure preserves evidence and never performs blind reset/restore/clean recovery.

## Execution Gate process boundary hardening

PR #19 was merged as:

`653b2b842e5f4c734b3390b1baec31c70f6ff3d7`

The prior direct `subprocess.run()` pytest path was removed. Gate test execution now uses the same process/resource containment model used by the rest of the execution stack.

The boundary explicitly:

- allowlists the resolved absolute pytest executable
- uses the active workspace as `cwd`
- forbids shell wrappers and interpreter inline launch shortcuts through the shared sandbox
- inherits process-group containment
- inherits timeout and output bounds
- inherits centralized secret redaction
- forwards only explicit `AGENT_*` environment variables requested by the gate test process
- fails closed when pytest cannot be resolved or launched

No filesystem, Git, remote, or shell mutation authority was added.

## Validation status

PR #19 was validated on the real Windows working tree at tested head `0a0d53dd04d160d2ec47bac124e2c1e806576841` before merge:

```text
python -m compileall -q .                         PASS
pytest -q test_execution_gate_process_boundary.py 6 passed
pytest -q test_process_output_redaction.py        3 passed
pytest -q                                        164 passed, 1 skipped
python orchestration_smoke_test.py                PASSED
git diff --check                               PASS
git status --short --branch                      CLEAN
```

The orchestration smoke proved both external phases locally:

```text
Leader output validation PASSED
Worker output validation PASSED
ORCHESTRATION SMOKE TEST PASSED
```

## Protected local state

The following remain local-only and must never be deleted, overwritten, truncated, renamed, or cleaned by synchronization:

```text
groq_keys.txt
openrouter_keys.txt
groq_keys.backup.txt
openrouter_keys.backup.txt
```

Other local `.env`, runtime state, machine credentials, caches, and preserved profile backups remain outside the GitHub promotion path.

Never use destructive synchronization such as blind `git clean -fd` or `git reset --hard`.

## Promotion record

```text
PR #19
Title: Harden Execution Gate with shared process boundary
Merge method: squash
Merge commit: 653b2b842e5f4c734b3390b1baec31c70f6ff3d7
Status: MERGED
```

The next engineering milestone should build on the established ProcessSandbox and mutation boundaries rather than bypassing them.