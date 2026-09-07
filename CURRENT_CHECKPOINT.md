# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`1188491d8ec502214d72fd677d312f765cfdd98e`

This squash merge promotes PR #39, hardening the final execution-authorization boundary so a typed validation verdict cannot be promoted from header fields alone; validation evidence, task identity, worker identity, and targets must agree before mutation admission.

## Verified architecture

The repository includes registry-driven leader/worker routing, runtime connection resilience, project understanding, context building, central leadership, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized secret/log redaction, the task-scoped Git mutation control plane, the Execution Gate process boundary, strict persisted mutation-result restoration, immutable transaction attestation, live evidence rebinding, machine-validated configuration authority, and registry-bound runtime health/lease state.

## Git mutation trust chain

```text
Passed ValidationVerdict
        +
isolated checkpoint
        +
exact FileChange targets/content
        +
validation evidence explicitly attests passed=True
        +
verdict/evidence task+worker identity agreement
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

`config_registry.py` fails closed when:

- leader or worker assignments are duplicated or overlap;
- a registry connection has no matching metadata;
- metadata contains an unassigned connection;
- a metadata key disagrees with the embedded connection ID;
- provider, status, active flag, or SHA-256 fingerprint shapes are malformed;
- an assigned connection has a provider inconsistent with its registry pool.

`connection_manager.py` preserves the authoritative role-source marker and continues to keep raw provider secrets outside the repository by default; only one-way fingerprints are stored in `connections.json`.

Legacy role/profile structures are no longer routing authorities. Compatibility names may remain in routers, but routing decisions are driven by `config/registry.json`.

## Runtime health/state boundary

The runtime health/state boundary is now promoted and tested.

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

Health/state input remains observation data, not configuration truth. Unknown connection IDs are ignored; wrong-provider health observations are rejected or ignored according to the component contract; model/tier mismatches do not become valid routing state; malformed and non-finite lease state is discarded; leader leases must match configured tier, model, provider, account, and task identity; worker leases must match configured role membership and standby semantics.

The implementation preserves shared leader accounts across the configured primary/failover pools: a connection may legitimately appear in both tiers, while each persisted lease must still bind to the tier/model actually recorded for that lease.

Worker execution adds a second authority check at the process-launch boundary: serialized worker assignments are not proof of identity. The boundary requires an authoritative active lease lookup, matches task/role/worker identity, rejects standby leases from direct execution, and rechecks the live lease after checkpoint establishment immediately before process launch.

The final mutation authorization boundary now also binds a passed `ValidationVerdict` to explicit positive validation evidence and matching task/worker identities before any Git mutation admission.

N-driven pools, stable connection IDs, safe-stop behavior on required-role exhaustion, and local-only runtime state remain intact.

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

PR #36 — runtime health and lease state authority hardening.

PR #38 — authoritative worker lease binding at the execution boundary.

PR #39 — validation verdict authority binding at mutation admission.

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

PR #36 was validated on the real Windows working tree before promotion:

```text
python -m compileall -q .                                  PASS
pytest -q test_registry_routers.py                          13 passed
pytest -q                                                   258 passed, 1 skipped
python repository_security_audit.py                        PASS
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

PR #38 was validated on the real Windows working tree before promotion:

```text
python -m compileall -q .                                  PASS
pytest -q test_worker_dispatch.py test_worker_execution.py test_worker_execution_process_sandbox.py 27 passed
pytest -q                                                   265 passed, 1 skipped
python repository_security_audit.py                        PASS
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

No GitHub Actions workflow runs were configured/available for PR #38; local Windows execution was therefore the promotion evidence.

PR #39 was validated on the real Windows working tree before promotion:

```text
python -m compileall -q .                                  PASS
pytest -q test_execution_authorization.py                  11 passed
pytest -q                                                   268 passed, 1 skipped
python repository_security_audit.py                        PASS
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

No GitHub Actions workflow runs were configured/available for PR #39; local Windows execution was therefore the promotion evidence.

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
