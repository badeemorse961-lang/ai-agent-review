# Git Commit Evidence Boundary

This component defines the pathname evidence contract used to verify a task-scoped Git commit.

## Evidence source

Committed targets must be inspected with a Git pathname-producing command that uses NUL termination. The intended shape is equivalent to:

```text
git diff-tree --no-commit-id --name-only --no-renames -r -z <commit>
```

The evidence parser treats only `NUL` as a record boundary. Newlines, spaces, quotes, arrows, and other pathname characters remain part of the pathname.

## Verification rules

The verifier:

1. rejects non-NUL-delimited evidence;
2. rejects unterminated NUL streams;
3. rejects empty pathname records;
4. normalizes only Windows separators (`\\` → `/`);
5. rejects duplicate evidence records;
6. rejects duplicate authorized targets; and
7. requires the committed pathname set to equal the authorized target set exactly.

This is evidence verification only. It does not perform Git mutation, network access, rollback, or authorization.

## Integration boundary

`git_commit_evidence.py` is an isolated verifier so the executor can adopt it without changing the established authorization, policy, sandbox, staging, or transaction flow. Until integrated, the existing executor remains the authoritative production path and this module provides independently tested evidence semantics.
