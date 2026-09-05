# Synchronization Rules

## Normal lifecycle
```text
GitHub
  ↓
fetch
  ↓
inspect
  ↓
safe apply
  ↓
preserve local-only state
  ↓
local validation
  ↓
tests
  ↓
verification
```

## Preconditions
Before sync:
- verify repository and branch
- inspect local working tree
- load protected-path policy
- detect uncommitted repository-controlled changes

## Protected state
Never delete or overwrite:
- secret files
- secret directories
- machine state
- local model stores
- explicitly protected runtime files

## Repository match
Repository-controlled files should match the selected Git revision after successful sync.

This is a controlled match, not a raw filesystem mirror.

## Conflicts
If a repository-controlled local file has uncommitted changes:
- stop before overwrite
- report the conflict
- preserve the local version
- require explicit resolution

Local-only files do not create repository conflicts.

## Verification
A new revision is not operationally accepted until:
1. sync
2. dependency check
3. syntax check
4. targeted tests
5. full regression
6. smoke test
7. final report

## Future sync agent
The eventual sync tool should support:
- dry-run
- protected-path report
- change preview
- safe apply
- verification
- rollback

`.gitignore` alone is not the complete safety mechanism.
