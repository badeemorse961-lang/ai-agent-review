# Task-Scoped Git Mutation Control Plane

## Purpose

The repository has two intentionally different Git capabilities:

1. `GitSafetyPolicy` protects the normal terminal path and remains inspection-only.
2. `GitMutationExecutor` is a separate mutation control plane for local repository staging and commits.

The second capability cannot be reached merely by asking the generic terminal executor to run a mutating Git command.

## Required authority chain

```text
Worker result
    ↓
Independent validation
    ↓
Internal execution authorization
    ↓
GitMutationExecutor
    ↓
GitMutationPolicy
    ↓
ProcessSandbox
    ↓
Git add -- <validated targets>
    ↓
verify staged target set
    ↓
Git commit -m <bounded message>
    ↓
verify HEAD + clean index/worktree + exact committed target set
```

The mutation layer does not independently authorize work. It consumes the existing validation and authorization evidence.

## Allowed mutations

Only two local operations are exposed:

- stage an exact non-empty set of workspace-relative validated targets;
- create one normal commit from that exact staged set with one bounded single-line commit message.

The control plane does not expose push, pull, fetch, reset, clean, checkout, switch, restore, merge, rebase, cherry-pick, stash, tag, remote, worktree, config injection, `--amend`, `--allow-empty`, `--no-verify`, signing overrides, or repository-scope overrides.

## Task scoping

Every mutation is bound to:

- a task ID;
- a worker ID;
- a passed `ValidationVerdict`;
- an isolated checkpoint attestation;
- an exact validated target set.

The target set in independent-validation evidence must equal the target set supplied by `FileChange` records. The Git policy then re-normalizes the paths and requires the generated command to match the validated request exactly.

Before invoking Git, each target is also required to resolve to an existing regular file inside the active workspace. Symlink/junction components are rejected so a path that only appears workspace-relative cannot redirect mutation outside the workspace.

## Preflight isolation

Before any Git mutation, the executor captures porcelain status and rejects the transaction when:

- the Git index already contains staged changes;
- any working-tree change exists outside the exact authorized target set;
- the repository state cannot be parsed into trustworthy evidence.

This prevents an agent task from silently absorbing unrelated human or another-agent changes.

A workspace-specific cross-process lock serializes local Git mutation transactions. A live or ambiguous lock fails closed. Only a lock whose recorded process ID is proven to have exited may be reclaimed automatically.

## Post-mutation verification

A commit is not considered successful merely because `git commit` returned zero.

Verification requires all of the following:

- post-commit Git status reports no staged files;
- post-commit Git status reports no working-tree files;
- the new `HEAD` resolves to a valid commit SHA;
- inspecting that commit shows exactly the authorized target set.

A commit hook can still perform repository-local side effects because hook execution is part of Git's normal commit behavior. The control plane therefore verifies the resulting commit after the fact and treats any target-set mismatch as a verification failure rather than automatically rewriting history or cleaning the repository.

Any ambiguity is a fail-closed verification error. The executor never performs a blind reset or cleanup to manufacture a clean result.

## Failure semantics

If staging or committing fails, staged evidence is intentionally preserved rather than automatically cleaned up. The caller must preserve the evidence and decide the next recovery action through an explicit higher-level rollback policy.

The mutation control plane does not delete local work, reset refs, discard files, or force-clean the repository after an ambiguous failure.

## Audit state

Successful transactions write `.agent_runtime/git_mutation_state.json`, which is covered by the repository ignore policy.

The audit record includes task identity, worker identity, target paths, before/after repository evidence, commit SHA, verification state, and a SHA-256 fingerprint of the commit message. The raw commit message is intentionally not persisted in the audit record.

## Security non-goals

This control plane does not provide:

- remote push authority;
- permission to rewrite existing history;
- OS-level filesystem isolation beyond the existing `ProcessSandbox` guarantees;
- authority to mutate undeclared external resources;
- authority to bypass independent validation or the Execution Gate;
- protection against a malicious Git hook beyond post-commit target verification.

## SAFE_STOP conditions

Stop without attempting cleanup when any of these occur:

- validation or authorization evidence is missing or fails;
- the active workspace does not match the process sandbox;
- Git is not explicitly allowlisted in the sandbox;
- a mutation target is missing, non-regular, or traverses a symlink/junction;
- preflight discovers unrelated changes or existing staged state;
- another live/ambiguous mutation lock is present;
- staged targets differ from the approved target set;
- commit fails, times out, or returns incomplete evidence;
- post-commit target verification differs from the authorized target set;
- repository status or commit evidence is truncated/untrustworthy.
