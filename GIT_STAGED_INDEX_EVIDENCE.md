# Git Staged-Index Evidence Boundary

The task-scoped Git mutation control plane must prove that the index contains exactly the authorized targets and exactly the validated blob content before commit.

## Evidence source

The authoritative pathname/object evidence shape is the NUL-delimited output of:

```text
git ls-files --stage -z -- <exact-target>
```

NUL is the only record boundary. Newlines, spaces, quotes, arrows, and other pathname characters remain part of the pathname.

## Verification rules

The verifier:

1. requires a supported object format (`sha1` or `sha256`);
2. requires NUL-delimited, NUL-terminated records;
3. rejects empty records and missing pathname separators;
4. validates index mode, object ID length/hex encoding, and merge stage;
5. rejects non-zero merge stages;
6. rejects duplicate pathname evidence;
7. rejects duplicate authorized targets;
8. requires the observed pathname set to equal the authorized target set exactly; and
9. optionally requires every observed object ID to equal a caller-provided expected object ID.

This component only interprets Git evidence. It does not stage, commit, execute arbitrary commands, access credentials, perform network operations, or authorize a mutation.

## Integration plan

The existing executor currently performs staged-index inspection through line-oriented `git ls-files --stage` parsing. This verifier is introduced as an independently tested evidence boundary so the integration can replace that parsing without changing the surrounding authorization, policy, sandbox, lock, or commit transaction flow.
