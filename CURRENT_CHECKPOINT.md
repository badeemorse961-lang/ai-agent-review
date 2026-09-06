# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`c5c6a37ada46f590a27b5be44c44fec2bc223e97`

This squash merge promotes pull request `#23`, which hardens post-commit Git pathname evidence with NUL-delimited parsing and exact authorized-target set verification.

Previous promoted milestone:

`f8db02667a79a8a172ca89a73d488311af5e2bcc` — PR #22 repository security invariant audit gate.

## Verified architecture

The repository includes registry-driven leader/worker routing, runtime connection resilience, project understanding, context building, central leadership, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized secret/log redaction, a separate task-scoped Git mutation control plane, and a dedicated Execution Gate process boundary.

The normal worker process path remains:

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

Gate-owned test execution is now:

```text
ExecutionGate
  ↓
ExecutionGateProcessRunner
  ↓
WorkspaceResourcePolicy
  ↓
ProcessSandbox
  ↓
pytest
```

The gate runner resolves an absolute pytest executable, allowlists that executable for the active workspace, executes shell-free with process-group containment and bounded timeout/output, and registers only explicit `AGENT_*` environment values for exact redaction. Ambient provider credentials remain excluded.

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

## Git commit pathname evidence hardening

PR #23 was merged as:

`c5c6a37ada46f590a27b5be44c44fec2bc223e97`

Post-commit committed-target verification now requests NUL-delimited pathname evidence using:

```text
git show --format= --name-only -z <commit>
```

The dedicated verifier requires NUL framing and a terminated stream, rejects empty records, rejects duplicate evidence, rejects duplicate authorized targets, normalizes only Windows separators, and requires the committed pathname set to equal the authorized target set exactly.

The integration tests additionally prove that line-oriented evidence is rejected, duplicate evidence is rejected, unexpected targets are rejected, and the executor issues the NUL-delimited inspection command.

This boundary is evidence-only. It adds no new authorization, process, shell, network, Git mutation, or rollback authority.

## Transaction hardening

The mutation lock is acquired before final mutable target validation. While the lock is held, target type, symlink/junction containment, UTF-8 decoding, and exact current-content equality with validated `FileChange.new_text` are revalidated immediately before staging.

After staging, the executor resolves the Git object format and verifies the exact staged blob object ID for every authorized target against the validated file content. An ambiguous index entry, unsupported object format, or staged-content mismatch stops before commit.

The transaction captures pre-mutation `HEAD`, proves it remains stable through final preflight, and after commit requires a distinct post-commit `HEAD` that matches the independently resolved commit identity used for exact target-set inspection.

Only structurally valid 40-character SHA-1 and 64-character SHA-256 Git object IDs are accepted.

Mutation failure preserves evidence and never performs blind reset/restore/clean recovery.

## Execution Gate process boundary hardening

PR #19 was merged as:

`653b2b842e5f4c734b3390b1baec31c70f6ff3d7`

The prior direct `subprocess.run()` pytest path was removed. Gate test execution now uses the same process/resource containment model used by the rest of the execution stack.

## Git status evidence parsing hardening

PR #20 was merged as:

`e452094a66c62af7042837d6604a40bac6743ef4`

The Git mutation snapshot path now obtains repository status with:

```text
git status --porcelain=v1 -z
```

and resolves the active branch independently with:

```text
git branch --show-current
```

The parser consumes NUL-delimited records instead of line-oriented human-readable status output. Filenames containing spaces, literal `->` sequences, quotes, or unusual UTF-8 characters therefore remain exact evidence rather than being reconstructed from textual separators. Rename/copy records preserve both the destination and source pathnames conservatively, so an unexpected path cannot disappear through ambiguous parsing.

Detached HEAD has no proven active branch identity and fails closed. Malformed NUL-separated records, missing rename/copy source pathnames, empty pathnames, unsupported status codes, or untrustworthy status evidence stop the mutation transaction rather than attempting recovery.

## Repository security invariant audit

PR #22 was merged as:

`f8db02667a79a8a172ca89a73d488311af5e2bcc`

The repository now contains a standard-library-only AST audit and CI gate that checks:

- direct, aliased, and imported subprocess execution paths outside approved execution boundaries
- `shell=True`, `os.system`, and `os.popen` primitives
- credential-shaped literals in production Python source
- continued `.gitignore` coverage for protected local credential filenames
- parseability of production Python source

The audit treats `process_sandbox.py` as the explicit low-level process-launch boundary while continuing to reject shell execution there. The legacy Git inspection code in `project_scanner.py` is not blanket-exempted; only four exact read-only Git commands are accepted, and only when arguments are literal/AST-proven constants with `shell=False`, `check=False`, and a positive explicit timeout. Other subprocess operations remain findings.

The audit is inspection-only and fail-closed. It adds no execution, Git mutation, network, or credential authority. CI runs both Python compilation and the security invariant audit on pull requests and pushes to `main`.

## Validation status

PR #23 was validated on the real Windows working tree at tested head `c0b657d4819283502e8640d206b82ba160eda654`:

```text
python -m compileall -q .                         PASS
pytest -q test_git_commit_evidence.py test_git_mutation_commit_evidence_integration.py
                                                14 passed
python repository_security_audit.py               PASS
pytest -q                                        194 passed, 1 skipped

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
PR #23
Title: Harden Git commit pathname evidence
Merge method: squash
Merge commit: c5c6a37ada46f590a27b5be44c44fec2bc223e97
Tested head: c0b657d4819283502e8640d206b82ba160eda654
Status: MERGED

Previous PR #22
Title: Add repository security invariant audit gate (rebased)
Merge method: squash
Merge commit: f8db02667a79a8a172ca89a73d488311af5e2bcc
Status: MERGED
```

The next engineering milestone should harden the transaction lock itself, preserving fail-closed concurrency semantics without introducing new mutation authority.