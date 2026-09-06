# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`6601b64918d240fcfaec9025d94bdb0e3ac82a7d`

This squash merge promotes pull request `#28`, adding real child-process verification of the OS-level workspace mutation lock and CI coverage for the concurrency boundary.

Previous promoted milestone:

`a5a6fe51da7157c8a042e544c1a8ca2cd3b25dd1` — PR #27 integrated the dedicated workspace lock and NUL-delimited staged-index evidence verifier into the authoritative `GitMutationExecutor` transaction.

## Verified architecture

The repository includes registry-driven leader/worker routing, runtime connection resilience, project understanding, context building, central leadership, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized secret/log redaction, a separate task-scoped Git mutation control plane, and a dedicated Execution Gate process boundary.

## Task-scoped Git mutation control plane

The promoted transaction is now:

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
OS-level WorkspaceMutationLock
        ↓
Git add -- <exact targets>
        ↓
git status --porcelain=v1 -z
        ↓
verify exact staged target set
        ↓
git ls-files --stage -z -- <exact targets>
        ↓
verify stage/path/object-ID evidence against validated content
        ↓
Git commit -m <bounded single-line message>
        ↓
post-commit HEAD + clean index/worktree verification
        ↓
git show --format= --name-only -z <commit>
        ↓
verify exact committed target set
```

Only local `stage` and `commit` operations are exposed. Remote mutation, history rewriting, destructive cleanup, branch switching, merge/rebase/cherry-pick/stash, configuration injection, amendment, signing overrides, and hook bypass are not exposed.

Every mutation consumes prior independent-validation and internal authorization evidence. It cannot self-authorize.

## Workspace mutation locking

PR #24 was merged as:

`3c6d0a05b8a8eea2fffecd7fc90a1fa266c300ee`

The dedicated `WorkspaceMutationLock` uses an operating-system advisory file lock keyed to the canonical workspace path. Windows uses `msvcrt.locking`; POSIX uses `fcntl.flock` with non-blocking exclusive acquisition.

The lock file is persistent and is not treated as an ownership marker. This removes the previous `PID check → stale unlink → recreate` sequence and its check-to-use race. A process crash releases the kernel-managed lock automatically.

The lock is a concurrency boundary only. It grants no authorization, Git, filesystem, process, network, shell, rollback, or credential authority.

PR #27 integrates this lock into the authoritative `GitMutationExecutor` critical section while preserving the executor compatibility adapter surface.

PR #28 adds real child-process verification of exclusion and crash-release behavior, making the concurrency property executable rather than relying only on same-process unit tests.

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

PR #27 now invokes this verifier once against the exact authorized target set and the expected object IDs derived from the validated `FileChange.new_text` content.

## Git commit pathname evidence hardening

Post-commit verification requests NUL-delimited pathname evidence using:

```text
git show --format= --name-only -z <commit>
```

The verifier requires terminated NUL framing, rejects empty records and duplicates, normalizes Windows separators only, and requires exact authorized-target equality.

The authoritative transaction retains this evidence check after commit.

## Transaction hardening

The mutation transaction captures pre-mutation `HEAD`, proves it remains stable through final preflight, verifies exact staged target and content evidence before commit, and after commit requires a distinct post-commit `HEAD` that matches the independently resolved commit identity used for exact committed-target inspection.

Staged-index evidence is task-scoped to one NUL-delimited query over the complete authorized target set instead of one line-oriented query per target. Pathname framing and target cardinality are therefore part of the evidence boundary rather than inferred from line parsing.

The workspace lock now has executable multi-process evidence for active-owner exclusion and crash-release behavior.

Mutation failure preserves evidence and never performs blind reset/restore/clean recovery.

## Repository security invariant audit

PR #22 was merged as:

`f8db02667a79a8a172ca89a73d488311af5e2bcc`

The repository security audit remains a standard-library-only AST gate for unsafe subprocess paths, shell execution primitives, credential-shaped literals, protected local credential filenames, and production-source parseability. CI runs compilation and the security invariant audit on pull requests and pushes to `main`, and now also executes the real cross-process workspace-lock test suite.

## Validation status

PR #28 was validated on the real Windows working tree at tested head `fa8a424a6c90b66819c91361f8f17cc574d39f42` before squash promotion:

```text
python -m compileall -q .                                  PASS
pytest -q test_workspace_mutation_lock.py \
          test_workspace_mutation_lock_multiprocess.py      8 passed
python repository_security_audit.py                        PASS
pytest -q                                                   214 passed, 1 skipped

git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

PR #27 was validated on the real Windows working tree at tested head `96e63747209c26142fc6e2639b350d853a688b17` before squash promotion:

```text
python -m compileall -q .                                  PASS
pytest -q focused mutation/evidence/lock suite               53 passed, 1 skipped
python repository_security_audit.py                        PASS
pytest -q                                                   211 passed, 1 skipped

git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

The earlier divergent PR #26 was not promoted. PR #27 was rebuilt from the coherent `main` checkpoint that already contained both `workspace_mutation_lock.py` and `git_staged_evidence.py`.

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
PR #28
Title: Harden workspace mutation lock with cross-process verification
Merge method: squash
Merge commit: 6601b64918d240fcfaec9025d94bdb0e3ac82a7d
Status: MERGED

PR #27
Title: Integrate mutation locking and staged-index evidence
Merge method: squash
Merge commit: a5a6fe51da7157c8a042e544c1a8ca2cd3b25dd1
Status: MERGED

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
Status: MERGED
```

The next engineering milestone should extend the real transaction evidence path itself: capture immutable task-scoped attestation metadata for staging and post-commit evidence, then verify that attestation survives serialization and remains bound to the same task, worker, targets, workspace, and commit identity before any further mutation authority is considered.