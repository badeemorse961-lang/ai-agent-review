# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`f19ad29f03d23a1cde894291de2a725b2937992f`

This squash merge promotes pull request `#25`, which hardens staged-index pathname and object evidence with NUL-delimited parsing and exact authorized-target verification.

Previous promoted milestone:

`3c6d0a05b8a8eea2fffecd7fc90a1fa266c300ee` — PR #24 workspace mutation lock hardening.

## Verified architecture

The repository includes registry-driven leader/worker routing, runtime connection resilience, project understanding, context building, central leadership, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized secret/log redaction, a separate task-scoped Git mutation control plane, and a dedicated Execution Gate process boundary.

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

## Workspace mutation locking

PR #24 was merged as:

`3c6d0a05b8a8eea2fffecd7fc90a1fa266c300ee`

The dedicated `WorkspaceMutationLock` now uses an operating-system advisory file lock keyed to the canonical workspace path. Windows uses `msvcrt.locking`; POSIX uses `fcntl.flock` with non-blocking exclusive acquisition.

The lock file is persistent and is not treated as an ownership marker. This removes the previous `PID check → stale unlink → recreate` sequence and its check-to-use race. A process crash releases the kernel-managed lock automatically.

The lock is a concurrency boundary only. It grants no authorization, Git, filesystem, process, network, shell, rollback, or credential authority.

## Git status evidence parsing hardening

PR #20 was merged as:

`e452094a66c62af7042837d6604a40bac6743ef4`

The Git mutation snapshot path obtains repository status with:

```text
git status --porcelain=v1 -z
```

and resolves the active branch independently with:

```text
git branch --show-current
```

The parser consumes NUL-delimited records, preserves complex pathnames, and handles rename/copy source paths conservatively. Detached HEAD and malformed or ambiguous evidence fail closed.

## Staged-index evidence hardening

PR #25 was merged as:

`f19ad29f03d23a1cde894291de2a725b2937992f`

`git_staged_evidence.py` defines the staged-index evidence contract for `git ls-files --stage -z`. It validates:

- NUL framing and required stream termination
- UTF-8 pathname decoding and separator normalization
- six-digit mode shape
- SHA-1 or SHA-256 object-ID shape
- merge stage (`0` only for ordinary staged mutation evidence)
- duplicate pathname evidence
- duplicate authorized targets
- exact staged target-set equality
- optional exact staged object-ID equality against validated expected content

The verifier is inspection-only and adds no mutation or authorization authority.

## Git commit pathname evidence hardening

PR #23 was merged as:

`c5c6a37ada46f590a27b5be44c44fec2bc223e97`

Post-commit verification requests NUL-delimited pathname evidence using:

```text
git show --format= --name-only -z <commit>
```

The verifier requires terminated NUL framing, rejects empty records and duplicates, normalizes Windows separators only, and requires exact authorized-target equality.

## Transaction hardening

The mutation transaction captures pre-mutation `HEAD`, proves it remains stable through final preflight, verifies exact staged target and content evidence before commit, and after commit requires a distinct post-commit `HEAD` that matches the independently resolved commit identity used for exact committed-target inspection.

Mutation failure preserves evidence and never performs blind reset/restore/clean recovery.

## Repository security invariant audit

PR #22 was merged as:

`f8db02667a79a8a172ca89a73d488311af5e2bcc`

The repository security audit remains a standard-library-only AST gate for unsafe subprocess paths, shell execution primitives, credential-shaped literals, protected local credential filenames, and production-source parseability. CI runs compilation and the security invariant audit on pull requests and pushes to `main`.

## Validation status

PR #25 was validated on the real Windows working tree at tested head `04085c2a24190e903f16917b1349cb4d8d975c9a` before its final parser adjustment; after adjustment the user verified:

```text
python -m compileall -q .                         PASS
pytest -q test_git_staged_evidence.py             9 passed
python repository_security_audit.py               PASS
pytest -q                                        208 passed, 1 skipped

git diff --check                               PASS
git status --short --branch                      CLEAN
```

PR #24 was validated on the real Windows working tree at tested head `48fa2b7d1440cea82685b38bef46a41d1188c5cc`:

```text
python -m compileall -q .                         PASS
pytest -q test_workspace_mutation_lock.py         5 passed
python repository_security_audit.py               PASS
pytest -q                                        199 passed, 1 skipped

git diff --check                               PASS
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
PR #25
Title: Harden staged-index evidence parsing
Merge method: squash
Merge commit: f19ad29f03d23a1cde894291de2a725b2937992f
Status: MERGED

PR #24
Title: Harden workspace mutation locking
Merge method: squash
Merge commit: 3c6d0a05b8a8eea2fffecd7fc90a1fa266c300ee
Status: MERGED

PR #23
Title: Harden Git commit pathname evidence
Merge method: squash
Merge commit: c5c6a37ada46f590a27b5be44c44fec2bc223e97
Status: MERGED
```

The next engineering milestone should integrate the dedicated workspace lock and staged-index evidence verifier into the authoritative `GitMutationExecutor` transaction, then exercise the complete concurrency + staging + commit-evidence flow on the real Windows workspace.