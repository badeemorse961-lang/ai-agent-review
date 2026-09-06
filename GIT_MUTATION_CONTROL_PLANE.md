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
verify current file content == validated FileChange.new_text
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

Every mutation is bound to a task ID, worker ID, passed `ValidationVerdict`, isolated checkpoint attestation, an exact validated target set, and the exact validated `FileChange.new_text` content at mutation time.

The target set in independent-validation evidence must equal the target set supplied by `FileChange` records. The Git policy then re-normalizes the paths and requires the generated command to match the validated request exactly.

Before invoking Git, each target is required to resolve to an existing regular UTF-8 text file inside the active workspace. Symlink/junction components are rejected so a path that only appears workspace-relative cannot redirect mutation outside the workspace. The current content must exactly equal the validated `new_text`; post-validation content drift is therefore a SAFE_STOP instead of an implicitly accepted change.

## Preflight isolation

Before any Git mutation, the executor captures porcelain status and rejects the transaction when the Git index contains staged changes, when working-tree changes exist outside the exact authorized target set, when repository status cannot be parsed into trustworthy evidence, or when a validated target's current content no longer matches its validated `new_text`.

A workspace-specific cross-process lock serializes local Git mutation transactions. A live or ambiguous lock fails closed. Only a lock whose recorded process ID is proven to have exited may be reclaimed automatically.

## Post-mutation verification

A commit is not considered successful merely because `git commit` returned zero. Verification requires a clean post-commit index and working tree, a valid new `HEAD` SHA, and an exact match between the authorized target set and the files recorded by the created commit.

A commit hook can still perform repository-local side effects. The control plane therefore treats any post-commit target-set mismatch as a verification failure rather than automatically rewriting history or cleaning the repository.

## Commit-message security

Commit messages become permanent Git history, so the mutation policy rejects messages that the centralized `SecretRedactor` classifies as credential-like material. This covers common bearer credentials, provider-shaped keys, generic `sk-*` forms, and secret-like assignments. Normal descriptive messages remain allowed, but recognizable credential material cannot enter repository history.

The successful audit record stores only a SHA-256 fingerprint of the accepted message; the raw message is not copied into local mutation audit state.

## Failure semantics

If staging or committing fails, staged evidence is intentionally preserved rather than automatically cleaned up. The caller must preserve the evidence and decide the next recovery action through an explicit higher-level rollback policy.

The mutation control plane does not delete local work, reset refs, discard files, or force-clean the repository after an ambiguous failure.

## Audit state

Successful transactions write `.agent_runtime/git_mutation_state.json`, which is covered by the repository ignore policy.

The audit record includes task identity, worker identity, target paths, before/after repository evidence, commit SHA, verification state, and a SHA-256 fingerprint of the commit message. The raw commit message is intentionally not persisted in the audit record.

## Security non-goals

This control plane does not provide remote push authority, permission to rewrite existing history, OS-level filesystem isolation beyond the existing `ProcessSandbox` guarantees, authority to mutate undeclared external resources, authority to bypass independent validation or the Execution Gate, or protection against a malicious Git hook beyond post-commit target verification.

## SAFE_STOP conditions

Stop without attempting cleanup when validation/authorization evidence is missing or fails, the workspace/sandbox boundary does not match, Git is not explicitly allowlisted, a target is missing/non-regular/not valid UTF-8 or traverses a symlink/junction, validated file content has drifted, preflight discovers unrelated or staged work, another live/ambiguous lock is present, staged targets differ from the approved set, the commit message contains credential-like material, commit evidence is incomplete, post-commit target verification differs, or repository evidence is truncated/untrustworthy.
