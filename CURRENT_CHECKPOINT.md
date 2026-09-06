# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`f323c26934d8e719d2b721b215486ec6ce42d047`

This squash merge promotes PR #34, making the static configuration registry authority machine-checkable and separating connection metadata from routing authority.

## Verified architecture

The repository includes registry-driven leader/worker routing, runtime connection resilience, project understanding, context building, central leadership, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized secret/log redaction, the task-scoped Git mutation control plane, the Execution Gate process boundary, strict persisted mutation-result restoration, immutable transaction attestation, live evidence rebinding, and machine-validated configuration authority.

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

`connections.json` is connection metadata only. Its role-source marker is aligned to `config/registry.json` and is not used as routing authority.

`config_registry.py` now fails closed when:

- leader or worker assignments are duplicated or overlap;
- a registry connection has no matching metadata;
- metadata contains an unassigned connection;
- a metadata key disagrees with the embedded connection ID;
- provider, status, active flag, or SHA-256 fingerprint shapes are malformed;
- an assigned connection has a provider inconsistent with its registry pool.

`connection_manager.py` preserves the authoritative role-source marker and continues to keep raw provider secrets outside the repository by default; only one-way fingerprints are stored in `connections.json`.

Legacy role/profile structures are no longer routing authorities. Compatibility names may remain in routers, but routing decisions are driven by `config/registry.json`.

## Runtime health/state boundary — next milestone

The next substantive gap is to make runtime health and persisted lease state strictly subordinate to the authoritative registry.

The target contract is:

```text
Authoritative registry
        +
Runtime health observations
        +
Local lease/failure state
        ↓
validated effective availability
        ↓
LeaderRouter / WorkerRouter
```

Health/state input is observation data, not configuration truth. Unknown connection IDs, wrong-provider observations, malformed state, stale leases, and state that cannot be safely reconciled with the registry must be ignored or fail closed according to the component contract rather than expanding routing authority.

This milestone must preserve N-driven pools, stable connection IDs, safe-stop behavior on required-role exhaustion, and local-only runtime state.

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

PR #34 — machine-validated configuration registry authority.

## Validation record

PR #33 was validated on the real Windows working tree before promotion:

```text
python -m compileall -q .                                  PASS
focused live-rebind/mutation suites                         62 passed, 1 skipped
python repository_security_audit.py                        PASS
pytest -q                                                   247 passed, 1 skipped
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

PR #34 was validated on the real Windows working tree before promotion:

```text
python -m compileall -q .                                  PASS
pytest -q test_config_registry.py test_connection_manager.py 13 passed
pytest -q                                                   251 passed, 1 skipped
python repository_security_audit.py                        PASS
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

## Promotion rule

For each architectural milestone:

```text
complete grouped implementation
    ↓
real Windows compile + focused tests + full regression
    ↓
security audit + diff review + working-tree verification
    ↓
merge to main
    ↓
update this checkpoint on main
```
