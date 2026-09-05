# CURRENT CHECKPOINT

## Status
Registry-driven router migration is **locally validated through repeated orchestration smoke** on the working branch:

`agent/registry-router-migration`

Current verified revision:

`51afefc Make orchestration smoke task IDs run-unique`

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
- `orchestration_smoke_test.py` now uses run-unique task IDs so persisted runtime state from an earlier interrupted run cannot collide with a later smoke run.
- Calculator regression defects exposed by the full test suite were repaired with minimal changes and its source encoding was normalized.

## Local validation results

Environment:

- Python: `3.12.10`
- `python -m compileall -q .`: PASS
- `python -m pytest -q`: `14 passed`
- `python leader_router.py`: registry synthetic test PASS
- `python worker_router.py`: registry synthetic test PASS
- `python orchestration_smoke_test.py`: PASS
- repeated `python orchestration_smoke_test.py` without deleting runtime state: PASS

Observed repeated orchestration results:

```text
Healthy Ultra leaders : 8
Healthy Super leaders : 10
Configured Groq workers: 15

Leader: successful; output validation PASSED
Worker: successful; output validation PASSED

ORCHESTRATION SMOKE TEST PASSED
Leader -> Worker -> Validation
Runtime failures -> alternate connection/model
Project files sent : NO
```

The earlier failure:

```text
LeaseError: Task already has a worker lease: SMOKE-CODER-001
```

was reproduced as a stale persisted task-lease collision. Removing that state allowed the smoke test to pass, and the subsequent run-unique task-ID fix was then validated by two consecutive successful runs without clearing state.

## Expansion readiness audit

The parameterized expansion tests continue to pass for:

`N=1,2,3,4,5,10,11,15,21,31,50,100`

and dynamic primary/failover simulations continue to pass for:

`N=5,11,21,31`

The audit still reports `REVIEW REQUIRED` because of known false-positive detections in:

- `expansion_readiness_audit.py` self-audit code;
- `project_state_classifier.py` CLI argument-count logic;
- literal task IDs / example data in `worker_router.py`.

These findings have not been promoted to architectural defects. The audit rules themselves require refinement so that operational configuration data and legitimate CLI/test constructs are distinguished from structural fixed-pool assumptions.

## Health variability observation

Repeated OpenRouter health checks showed that individual account/model outcomes can vary between runs. Examples included accounts that failed with `INVALID_RESPONSE` on one run and later succeeded, while other accounts changed status between runs.

This is evidence that a health snapshot is time-dependent and must not be treated as permanent account failure. Runtime selection should continue to rely on current validated responses, retry/failover behavior, and runtime failure tracking.

## Important synchronization state

Protected local secret files remain outside repository synchronization control:

```text
groq_keys.txt
openrouter_keys.txt
groq_keys.backup.txt
openrouter_keys.backup.txt
```

Local generated profile copies remain preserved outside the repository at the protected local backup location created during branch synchronization. They must not be deleted merely because they are absent from Git.

Do not discard, reset, or overwrite unrelated intentional local work.

## Promotion status

The registry/router/orchestration migration is operationally validated on the synchronized local branch, but it is **not yet promoted to `main`**.

The branch currently stands:

- `28` commits ahead of `main`
- `0` commits behind `main`

Before promotion:

```text
verified smoke
    ↓
expansion audit refinement
    ↓
dependency / architecture review
    ↓
update AI_AGENT_HANDOFF.md with final verified checkpoint
    ↓
create / review pull request
    ↓
merge/promote to main
```

## Next exact action

Refine `expansion_readiness_audit.py` so its high-severity findings distinguish true structural fixed-size assumptions from legitimate code such as CLI argument counts, self-audit implementation details, and test/example literals. Then rerun the full validation suite and inspect the complete diff for:

- stale profile dependencies;
- hardcoded pool-size assumptions;
- remaining runtime-state/schema incompatibilities;
- obsolete legacy artifacts;
- secret-handling regressions.

Do not reintroduce generated profile files as routing sources.

## Source of truth

Static routing configuration:

`config/registry.json`

Registry loader/validator:

`config_registry.py`

Runtime health/state:

local runtime data only

Generated profiles must not become a second source of routing truth.
