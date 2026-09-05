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

### Local API-key files
If a local API-key file already exists, synchronization or repository cleanup MUST preserve it even when that file is absent from Git or absent from the selected repository revision.

Normal repository synchronization MUST NOT:
- delete the existing key file;
- overwrite its contents;
- truncate it;
- rename or move it;
- replace it with an empty/generated file;
- treat its absence from Git as permission to remove it locally.

For the current setup this includes, at minimum:
```text
groq_keys.txt
openrouter_keys.txt
groq_keys.backup.txt
openrouter_keys.backup.txt
```

Only an explicit human-directed local secret-management operation may change or remove such a file. This rule is independent of `.gitignore` and applies to sync tools, cleanup routines, and other repository-update automation.

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
