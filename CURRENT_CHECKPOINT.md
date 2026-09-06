# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`a5a61d7fcb36efe177c4f779204e4b87b8281c22`

This squash merge promotes pull request `#18`, which hardens the task-scoped Git mutation transaction without expanding mutation authority.

Previous promoted mutation baseline:

`efe47c8e5a58bbb0c17d21b9474662f1bfa72654` — PR #17.

## Verified architecture

The repository includes registry-driven leader/worker routing, runtime connection resilience, project understanding, context building, central leadership, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized secret/log redaction, and a separate task-scoped Git mutation control plane.

The normal worker process path is:

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

## Task-scoped Git mutation control plane

The promoted control plane is:

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

## Validation status

PR #18 was validated on the real Windows working tree at the tested branch head before merge:

```text
python -m compileall -q .                         PASS
focused mutation/security suite                  42 passed, 1 skipped
full regression suite                             158 passed, 1 skipped
git diff --check                                  PASS
python config_registry.py                         VALID
python leader_router.py                           REGISTRY TEST PASSED
python worker_router.py                           REGISTRY TEST PASSED
python orchestration_smoke_test.py                PASSED
git status --short --branch                      CLEAN
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
PR #18
Title: Harden task-scoped Git mutation transaction evidence
Merge method: squash
Merge commit: a5a61d7fcb36efe177c4f779204e4b87b8281c22
Status: MERGED
```

The next engineering milestone should build on this hardened mutation boundary rather than widening generic terminal Git authority.
