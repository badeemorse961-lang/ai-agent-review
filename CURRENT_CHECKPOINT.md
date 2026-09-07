# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`fd5deca992798d0e519027c2f25f77ed07ee1d2f`

PR #41 hardens the Central Leader planning boundary: after model transport returns, the authoritative router snapshot is re-read and the original leader lease must still exist with the exact provider, account, model, tier, and task identity. A disappeared or rebound lease is a safety stop; the model result is never accepted under a new leader identity.

## Verified architecture

The repository includes registry-driven leader/worker routing, runtime connection resilience, project understanding, context building, central leadership, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized secret/log redaction, the task-scoped Git mutation control plane, the Execution Gate process boundary, strict persisted mutation-result restoration, immutable transaction attestation, live evidence rebinding, machine-validated configuration authority, registry-bound runtime health/lease state, authoritative worker lease binding, validation verdict authority binding, and explicit autonomous leader start authorization.

## Git mutation trust chain

```text
Passed ValidationVerdict
        + isolated checkpoint
        + exact FileChange targets/content
        + validation evidence explicitly attests passed=True
        + verdict/evidence task+worker identity agreement
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

`config/registry.json` is authoritative for leader pools, worker roles, and connection assignment. `connections.json` is connection metadata only; its role-source marker is aligned to the registry and is not routing authority.

`config_registry.py` fails closed on duplicate/overlapping assignments, missing or unassigned metadata, metadata-key/embedded-ID disagreement, malformed provider/status/active/fingerprint fields, and provider mismatch with the assigned registry pool. Raw provider secrets remain outside the repository by default; only one-way fingerprints are stored in `connections.json`.

## Runtime health/state boundary

```text
Authoritative registry + runtime health observations + local lease/failure state
        ↓
validated effective availability
        ↓
LeaderRouter / WorkerRouter
```

Health/state input is observation data, not configuration truth. Unknown IDs are ignored; wrong-provider observations are rejected/ignored according to component contract; model/tier mismatches do not become routing state; malformed/non-finite leases are discarded. Leader leases must match configured tier/model/provider/account/task identity. Worker leases must match configured role membership and standby semantics.

Worker execution requires an authoritative active lease lookup, matches task/role/worker identity, rejects standby leases from direct execution, and rechecks the live lease after checkpoint establishment immediately before process launch. Mutation authorization also binds a passed `ValidationVerdict` to explicit positive evidence and matching task/worker identities before Git mutation admission.

## Central Leader authority boundary

`CentralLeader` treats model/evidence context as untrusted input. A project state in the allowed planning set does not itself grant autonomous start authority. `project.autonomous_start_allowed` must be explicitly `True`; missing/false is a safety stop, and this authority remains distinct from execution and mutation authority.

During planning, the original `LeaderRequest` identity is re-bound against a fresh authoritative router snapshot after transport. Disappearance or any provider/account/model/tier/task rebind invalidates the model output.

## Project and safety rules

UNKNOWN and unresolved CONFLICT are safety stops. Confirmed breakage means REPAIR. Model output is untrusted. Local tests determine executable reality. Secrets remain outside Git history and normal child environments. Generic terminal Git access remains inspection-only. High-risk authority is separated explicitly.

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

PR #40 — explicit autonomous leader start authorization at the Central Leader boundary.

PR #41 — live Central Leader lease rebinding after model transport.

## Validation record

PR #33 — real Windows working tree:

```text
python -m compileall -q .                                  PASS
focused live-rebind/mutation suites                        62 passed, 1 skipped
python repository_security_audit.py                         PASS
pytest -q                                                   247 passed, 1 skipped
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

PR #34 — real Windows working tree:

```text
python -m compileall -q .                                  PASS
pytest -q test_config_registry.py test_connection_manager.py 13 passed
pytest -q                                                   251 passed, 1 skipped
python repository_security_audit.py                         PASS
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

PR #36 — real Windows working tree:

```text
python -m compileall -q .                                  PASS
pytest -q test_registry_routers.py                          13 passed
pytest -q                                                   258 passed, 1 skipped
python repository_security_audit.py                         PASS
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

PR #38 — real Windows working tree:

```text
python -m compileall -q .                                  PASS
pytest -q test_worker_dispatch.py test_worker_execution.py test_worker_execution_process_sandbox.py 27 passed
pytest -q                                                   265 passed, 1 skipped
python repository_security_audit.py                         PASS
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

No GitHub Actions workflow runs were configured/available for PR #38; local Windows execution was therefore the promotion evidence.

PR #39 — real Windows working tree:

```text
python -m compileall -q .                                  PASS
pytest -q test_execution_authorization.py                   11 passed
pytest -q                                                   268 passed, 1 skipped
python repository_security_audit.py                         PASS
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

No GitHub Actions workflow runs were configured/available for PR #39; local Windows execution was therefore the promotion evidence.

PR #40 — real Windows working tree:

```text
python -m compileall -q .                                  PASS
pytest -q test_central_leader.py                            7 passed
pytest -q                                                   269 passed, 1 skipped
python repository_security_audit.py                         PASS
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

No GitHub Actions workflow runs were configured/available for PR #40; local Windows execution was therefore the promotion evidence.

PR #41 — real Windows working tree:

```text
python -m compileall -q .                                  PASS
pytest -q test_central_leader.py                            10 passed
pytest -q                                                   272 passed, 1 skipped
python repository_security_audit.py                         PASS
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

No GitHub Actions workflow runs were configured/available for PR #41; local Windows execution was therefore the promotion evidence.

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
