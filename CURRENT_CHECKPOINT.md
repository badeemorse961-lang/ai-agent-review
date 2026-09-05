# CURRENT CHECKPOINT

## Status
Registry-driven router migration has reached a **green local validation checkpoint** on the working branch:

`agent/registry-router-migration`

Executable code was locally validated at:

`97f282eb7c00e8f219f3d4defd40d87fd959b661`

The latest local validation cycle completed successfully after the final compatibility refinement.

## Completed in this checkpoint

- LeaderRouter derives provider, models, and leader pools from `config/registry.json`.
- WorkerRouter derives provider, model, and role pools from `config/registry.json`.
- Worker runtime failures are tracked separately from external health so a health refresh does not erase runtime failures.
- LeaderFailover is a compatibility facade over LeaderRouter; there is one authoritative leader runtime.
- Leader health-check configuration is derived from the registry.
- Groq worker health-check configuration is derived from the registry.
- Generated profile files are not routing authorities and the generator scripts `leader_profiles.py` and `worker_profiles.py` are retired.
- Legacy leader discovery utility `discover_leader_models.py` and generated artifact `leader_capabilities.json` are removed from the working branch because routing is registry-driven and no legitimate dependency was found.
- Registry-driven router tests exist in `test_registry_routers.py`.
- Runtime connection resilience policy is documented in `RUNTIME_CONNECTION_RESILIENCE.md`.
- WorkerRouter provides a compatibility alias `reset_runtime()` for legacy callers while `reset_runtime_state()` remains the underlying implementation.
- `orchestration_smoke_test.py` uses run-unique task IDs so persisted runtime state from an earlier interrupted run cannot collide with a later smoke run.
- Calculator regression defects exposed by the full test suite were repaired with minimal changes and source encoding was normalized.
- Expansion Readiness Audit v2 distinguishes structural fixed-size assumptions from legitimate CLI/test/self-audit constructs.
- Added regression coverage for the expansion audit and compatibility behavior.
- Final LeaderFailover compatibility repair removed a dependency on a non-existent `LeaderRouter.active_leases()` API by using the router's authoritative `snapshot()["leases"]` state instead.

## Local validation results at executable checkpoint

Environment:

- Python: `3.12.10`
- `python -m pytest -q`: `19 passed`
- `python leader_failover.py`: PASS / READY

The final compatibility regression now passes together with the complete local test suite.

## Expansion readiness audit

Parameterized expansion tests passed for:

`N=1,2,3,4,5,10,11,15,21,31,50,100`

Dynamic primary/failover simulations passed for:

`N=5,11,21,31`

The audit returned:

`EXPANSION READINESS AUDIT PASSED ✅`

It may still emit MEDIUM findings for runtime result metadata such as `$.leader.attempts = 1`. Those are execution observations, not routing configuration or fixed pool capacity.

## Lease collision repair

An earlier orchestration run failed with:

```text
LeaseError: Task already has a worker lease: SMOKE-CODER-001
```

This was reproduced as a stale persisted task-lease collision. The correct fix was **not** to weaken WorkerRouter lease protection. Instead, orchestration smoke task IDs were made run-unique.

The fix was then validated by consecutive successful smoke runs without clearing runtime state.

## Compatibility review refinement

Final review identified one compatibility semantic that needed preservation: the legacy `LeaderFailover.reset()` contract returned the active primary connection after reset. The facade was adjusted so reset clears runtime failures and then keeps the newly acquired primary compatibility lease active rather than immediately releasing it.

A regression test verifies:

```text
reset()
→ returns first primary connection
→ current_connection() matches it
→ current_model() is primary model
→ current_tier() == primary
→ state() == READY

failover("compatibility_test_failure")
→ moves to the next available primary connection
→ remains READY on the primary tier
```

The final compatibility cycle passed with the full suite at 19/19.

## Health variability observation

Repeated OpenRouter health checks showed that individual account/model outcomes can vary between runs. Accounts can fail with `INVALID_RESPONSE` on one run and later succeed, while other accounts can change status between runs.

Therefore a health snapshot is time-dependent and must not be treated as permanent account failure. Runtime selection continues to rely on current validated responses, retry/failover behavior, and runtime failure tracking.

## Important synchronization state

Protected local secret files remain outside repository synchronization control:

```text
groq_keys.txt
openrouter_keys.txt
groq_keys.backup.txt
openrouter_keys.backup.txt
```

Local generated profile copies remain preserved outside repo synchronization control at the protected local backup location created during branch synchronization. They must not be deleted merely because they are absent from Git.

Do not discard, reset, or overwrite unrelated intentional local work.

## Promotion status

Pull request:

`#1 — Migrate routing to registry and validate N-driven orchestration`

Current branch state:

- `38` commits ahead of `main`
- `0` commits behind `main`
- PR remains open and unmerged
- No submitted reviews or review threads are currently present
- No commit status checks are currently reported for the latest head

Current branch head:

`97f282eb7c00e8f219f3d4defd40d87fd959b661`

Required promotion sequence:

```text
local validation green
    ↓
complete diff review
    ↓
dependency / architecture review
    ↓
security / secret-boundary review
    ↓
PR review
    ↓
merge to main
```

## Architecture review conclusion so far

Executable evidence currently supports these conclusions:

- registry-driven leader and worker routing functions;
- global worker lease protection remains intact;
- runtime failover works;
- orchestration is repeatable with persisted state;
- expansion readiness coverage passes;
- full regression passes;
- LeaderFailover compatibility behavior is preserved without creating a second runtime authority;
- generated profile/discovery artifacts are no longer routing authorities.

A separate production-hardening milestone remains for `connection_manager.py`: move secret-file location outside permanent repository-relative paths and make key rotation preserve stable connection identity independently of secret-file line order.

## Source of truth

Static routing configuration:

`config/registry.json`

Registry loader/validator:

`config_registry.py`

Runtime health/state:

local runtime data only

Generated profiles must not become a second source of routing truth.
