# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`efe47c8e5a58bbb0c17d21b9474662f1bfa72654`

This squash merge promotes pull request `#17`, the task-scoped Git mutation control plane.

The current engineering milestone is the transaction-hardening branch `agent/git-mutation-transaction-hardening`, based directly on this main baseline.

## Verified architecture

The repository now includes registry-driven leader/worker routing, runtime connection resilience, project understanding, context building, central leadership, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized secret/log redaction, and a separate task-scoped Git mutation control plane.

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

Target paths must be workspace-relative, non-duplicate, existing regular UTF-8 files with no symlink/junction escape. Current contents must equal the validated `FileChange.new_text` before staging.

The control plane refuses unrelated working-tree or pre-staged index state, serializes same-workspace mutation through a fail-closed lock, verifies the staged target set before commit, verifies the staged blob identity against the validated content, and verifies post-commit HEAD/index/worktree/target-set evidence.

Commit messages are bounded single-line values and are rejected when `SecretRedactor` identifies credential-like material, preventing recognizable credentials from entering Git history.

Mutation failure preserves staged evidence and never runs blind `reset`, `restore`, or `clean` recovery.

## Transaction-hardening milestone

This milestone does not add repository mutation authority. It closes validation/index race windows and strengthens repository identity evidence inside the already promoted boundary.

The workspace-specific mutation lock is now entered before final mutable target validation. While the lock is held, the executor revalidates target type, symlink/junction containment, UTF-8 decoding, and exact current-content equality with the validated `FileChange.new_text` immediately before staging.

After staging, the executor resolves the repository object format, computes the expected Git blob object ID for each validated `FileChange.new_text`, and compares it with the exact staged index entry reported by Git. An ambiguous index entry, unsupported object format, or content mismatch is a fail-closed verification stop before commit.

The transaction captures the pre-mutation `HEAD`, verifies it remains stable through final preflight, and after commit requires a distinct post-commit `HEAD` that matches the independently resolved commit identity used for exact target-set inspection.

Only structurally valid 40-character SHA-1 and 64-character SHA-256 Git object IDs are accepted as repository identities.

Regression coverage was added for lock ordering, staged-index content integrity, HEAD advancement, and resolved-HEAD consistency.

## Validation status

The promoted PR #17 was already validated on a real Windows working tree before merge:

```text
focused mutation/security suite → 37 passed, 1 skipped
full regression suite             → 153 passed, 1 skipped
compileall                         → PASS
git diff --check                   → PASS
config registry                    → VALID
leader router synthetic            → PASS
worker router synthetic            → PASS
orchestration smoke                → PASS
working tree                       → CLEAN
```

The transaction-hardening branch requires a fresh Windows validation gate before promotion of this new code.

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

## Promotion rule

```text
complete grouped implementation
    ↓
Windows compile + focused tests + full suite
    ↓
diff review
    ↓
security / architecture review
    ↓
merge
    ↓
update CURRENT_CHECKPOINT.md with actual merge commit
```
