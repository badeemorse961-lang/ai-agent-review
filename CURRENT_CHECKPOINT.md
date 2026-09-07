# CURRENT CHECKPOINT

## Baseline

`main` is the authoritative GitHub baseline.

Latest merged implementation baseline:

`9d0be9c8b67e975fc0a1fe0d286c663933842283`

PR #42 binds mutation authorization to the authoritative execution checkpoint identity: every independently validated `ExecutionResult` must carry a non-empty `checkpoint_id`; that identity is copied into `ValidationVerdict.evidence`; and `ExecutionAuthorizationBoundary` requires the isolated authorization checkpoint identity to match the validation evidence exactly. Missing/rebound checkpoint identities are safety stops. Existing legacy mutation fixtures remain compatible only when `transaction_id` exactly matches the verdict task identity and validation evidence explicitly attests `validated=True`.

PR #43 restores the repository's GitHub Actions security-evidence path by installing the declared test dependency before the cross-process workspace-lock suite. The resulting workflow run passed dependency installation, Python compilation, repository security audit, and the cross-process mutation-lock tests.

PR #45 establishes the canonical end-to-end orchestration composition over the existing authority boundaries. The coordinator composes project understanding, Central Leader, plan decomposition, worker dispatch, guarded worker execution, independent validation, execution authorization, and the Execution Gate without collapsing their authority responsibilities. Deterministic integration coverage includes the normal mutating path plus adversarial authority/evidence failures. No plan-wide atomic rollback claim was added.

## Verified architecture

The repository includes registry-driven leader/worker routing, runtime connection resilience, project understanding, context building, central leadership, plan/decomposition, worker dispatch, guarded worker execution, independent validation, internal execution authorization, resource/process sandboxing, policy-first terminal execution, inspection-only Git terminal safety, centralized secret/log redaction, the task-scoped Git mutation control plane, the Execution Gate process boundary, strict persisted mutation-result restoration, immutable transaction attestation, live evidence rebinding, machine-validated configuration authority, registry-bound runtime health/lease state, authoritative worker lease binding, validation verdict authority binding, explicit autonomous leader start authorization, live Central Leader lease rebinding, execution-checkpoint identity binding at mutation authorization, and canonical orchestration composition from project understanding through Execution Gate approval.

## Git mutation trust chain

```text
Passed ValidationVerdict
        + isolated checkpoint
        + exact FileChange targets/content
        + validation evidence explicitly attests passed=True
        + verdict/evidence task+worker identity agreement
        + execution checkpoint identity matches validation evidence
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

Worker execution requires an authoritative active lease lookup, matches task/role/worker identity, rejects standby leases from direct execution, and rechecks the live lease after checkpoint establishment immediately before process launch. Mutation authorization binds a passed `ValidationVerdict` to explicit positive evidence, matching task/worker identities, and the exact execution checkpoint identity before Git mutation admission.

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

PR #42 — execution-checkpoint identity binding at mutation authorization.

PR #43 — restored GitHub Actions security-audit test dependency.

PR #45 — canonical end-to-end orchestration composition and deterministic integration acceptance.

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
pytest -q                                                   269 passed, 1 skipped
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

PR #42 — real Windows working tree:

```text
python -m compileall -q .                                  PASS
pytest -q test_independent_validation.py test_execution_authorization.py 25 passed
pytest -q                                                   277 passed, 1 skipped
python repository_security_audit.py                         PASS
git diff --check                                            PASS
 git status --short --branch                                 CLEAN
```

No GitHub Actions workflow runs were configured/available for PR #42; local Windows execution was therefore the promotion evidence.

PR #43 — GitHub Actions security-audit evidence:

```text
Install test dependency                                 PASS
python -m compileall -q .                               PASS
python repository_security_audit.py                      PASS
python -m pytest -q test_workspace_mutation_lock.py \
  test_workspace_mutation_lock_multiprocess.py           PASS
```

PR #43 is evidence-pipeline hardening only; it does not replace the real Windows validation requirement for architectural/runtime milestones.

PR #45 — real Windows acceptance evidence:

```text
python -m compileall -q .                                  PASS
pytest -q test_orchestration.py                             8 passed
pytest -q                                                   285 passed, 1 skipped
python repository_security_audit.py                         PASS
python orchestration_smoke_test.py                          PASS
  Healthy Ultra leaders : 8
  Healthy Super leaders : 10
  Configured Groq workers: 15
  Leader: OR-02 / nvidia/nemotron-3-ultra-550b-a55b:free / ULTRA
  Leader output validation                                PASS
  Worker: GROQ-01 / openai/gpt-oss-120b / standby=False
  Worker output validation                                PASS
  Project files sent                                       NO
git diff --check                                            PASS
git status --short --branch                                 CLEAN
```

PR #45 is the accepted canonical composition evidence. The focused integration suite exercises the real worker execution, independent validation, and execution-authorization/Execution-Gate boundaries through deterministic adapters, while the provider/router smoke remains a separate connectivity/failover check. The accepted architecture does not claim plan-wide atomic rollback across multiple task transactions.

## Future operational readiness — Dynamic Connection Onboarding & Auto-Assignment

Tracking issue: **#46 — Future readiness: Dynamic Connection Onboarding & Auto-Assignment**.

Current assessment: **CONFIGURATION-DRIVEN ONLY**.

The repository already supports variable-length registry-defined leader/worker pools, uniqueness and assignment validation, provider consistency checks, runtime health separation, and router-side exclusion of unavailable connections. This proves configuration-driven expansion, not automatic onboarding.

The following are **not currently verified** as a single end-to-end capability: automatic capability discovery for a newly added connection, deterministic classification from validated metadata/policy/registry, automatic pool insertion without manual registry maintenance, onboarding health admission, and automatic quarantine/re-admission lifecycle.

This requirement is intentionally not a current milestone and must not interrupt canonical-orchestration acceptance. When formally evaluated, record exactly one status:

```text
AUTO-ONBOARDING VERIFIED
CONFIGURATION-DRIVEN ONLY
MISSING IMPLEMENTATION
```

The requirement must preserve these invariants: `config/registry.json` remains routing authority; pool sizes stay N-driven; connection IDs stay unique and stable; every connection has exactly one valid routing assignment; provider/model/role assignment remains policy-consistent; runtime health/state never becomes configuration authority; secrets remain outside Git; and onboarding classification is deterministic rather than guessed from a model name.

## Current readiness

Canonical end-to-end orchestration is now promoted and verified. Provider/router smoke remains independently verified. Dynamic connection onboarding remains a future operational-readiness requirement and is **not** part of PR #45 acceptance.

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
