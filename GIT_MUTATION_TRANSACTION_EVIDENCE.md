# Git Mutation Transaction Evidence

The authoritative `GitMutationExecutor` transaction now composes three task-scoped evidence boundaries:

```text
OS-level WorkspaceMutationLock
        ↓
before snapshot + preflight
        ↓
validated target/content recheck
        ↓
Git add -- <exact targets>
        ↓
git status --porcelain=v1 -z
        ↓
git ls-files --stage -z -- <exact targets>
        ↓
validated FileChange content → expected Git object IDs
        ↓
Git commit -m <bounded message>
        ↓
post-commit HEAD + clean-state verification
        ↓
git show --format= --name-only -z <commit>
        ↓
exact committed target-set verification
```

The workspace lock serializes the mutation critical section and is kernel-managed. The staged-index verifier and commit pathname verifier consume NUL-delimited Git pathname evidence and fail closed on malformed framing, duplicates, unexpected targets, unsupported metadata, or mismatched content/object identity.

These components provide evidence and ordering only. Existing authorization, policy, process sandbox, validation, checkpoint, and rollback/evidence-preservation controls remain authoritative.
