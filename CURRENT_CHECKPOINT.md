# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`f95e47eb3aec39fc68b9e19c79072714d2c504cf`

This squash merge promotes PR #33, adding an inspection-only live Git evidence rebinding boundary for restored `GitMutationResult` records.

The live rebind contract proves the same canonical workspace, process-sandbox binding, active branch, attested `HEAD`, clean index/worktree, exact committed target set, and matching committed-evidence SHA-256 digest. It performs no mutation, recovery, branch switching, or authorization.

## Verified architecture

The repository includes registry-driven leader/worker routing, runtime connection resilience, project understanding, context building, central leadership, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized secret/log redaction, the task-scoped Git mutation control plane, the Execution Gate process boundary, strict persisted mutation-result restoration, immutable transaction attestation, and live evidence rebinding.

## Git mutation trust chain

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
NUL-delimited staged-target/content evidence
        ↓
Git commit -m <bounded message>
        ↓
post-commit HEAD + clean index/worktree
        ↓
NUL-delimited committed-target evidence
        ↓
immutable transaction attestation
        ↓
atomic audit persistence
        ↓
strict result restoration
        ↓
inspection-only live evidence rebind before later trust
```

The mutation control plane exposes only local `stage` and `commit`. Remote mutation, destructive cleanup, history rewriting, branch switching, configuration injection, amendment, and hook bypass remain outside its authority.

## Configuration authority

`config/registry.json` is the authoritative source for leader pools, worker roles, and connection assignment.

`connections.json` is connection metadata only. Its `role_source` marker must be `config/registry.json` and must not reference a legacy role file.

The current engineering milestone hardens `config_registry.py` so the declared invariants are machine-checked:

- every leader/worker assignment is unique;
- leader and worker pools are disjoint;
- every registry connection has corresponding metadata;
- no metadata connection exists without an authoritative assignment;
- metadata keys match their embedded connection IDs;
- provider, status, active flag, and SHA-256 key fingerprint fields have validated shapes;
- leader and worker providers match their assigned connection metadata.

`connection_manager.py` preserves the authoritative role-source marker when loading or saving connection metadata and does not treat role information as routing authority.

## Project and safety rules

UNKNOWN and unresolved CONFLICT are safety stops. Confirmed breakage means REPAIR. Model output is untrusted. Local tests determine executable reality. Secrets remain outside Git history and normal child environments. Generic terminal Git access remains inspection-only. Normal development is autonomous inside the active workspace; high-risk authority is separated explicitly.

Never use destructive synchronization such as `git clean -fd` or `git reset --hard`.

## Protected local state

The following remain local-only and must never be deleted, overwritten, truncated, renamed, or cleaned by synchronization:

```text
groq_keys.txt
openrouter_keys.txt
groq_keys.backup.txt
openrouter_keys.backup.txt
```

## Previous promoted milestones

PR #24 — OS-level workspace mutation locking.

PR #25 — NUL-delimited staged-index evidence hardening.

PR #27 — authoritative integration of locking and staged evidence.

PR #28 — cross-process lock exclusion/crash-release evidence.

PR #30 — immutable task-scoped transaction attestation primitive.

PR #31 — attestation integration into authoritative Git mutation results.

PR #32 — strict whole-result restoration boundary.

PR #33 — live Git evidence rebinding.

## Validation record

The latest real Windows validation completed on the live-rebind branch before promotion:

```text
python -m compileall -q .                                  PASS
focused live-rebind/mutation suites                         62 passed, 1 skipped
python repository_security_audit.py                        PASS
pytest -q                                                   247 passed, 1 skipped
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

That evidence applies to merged baseline `f95e47eb3aec39fc68b9e19c79072714d2c504cf` plus the promoted live-rebind tests.

## Current milestone

`agent/harden-config-authority`

Goal: make the static routing authority and connection metadata contract machine-validated so stale role sources, unassigned connections, identity mismatches, and malformed connection metadata fail closed before routing decisions are made.

Required promotion sequence:

```text
complete grouped implementation
    ↓
real Windows compile + focused configuration/connection tests + full regression
    ↓
security audit + diff review + working-tree verification
    ↓
merge to main
    ↓
update this checkpoint on main
```
