# CURRENT CHECKPOINT

## Status
Registry-driven router migration is **locally validated through orchestration smoke** on the working branch:

`agent/registry-router-migration`

Current verified revision:

`6e0557a Add WorkerRouter reset_runtime compatibility alias`

## Completed in this checkpoint

- LeaderRouter derives provider, models, and leader pools from `config/registry.json`.
- WorkerRouter derives provider, model, and role pools from `config/registry.json`.
- Worker runtime failures are tracked separately from external health so a health refresh does not erase runtime failures.
- LeaderFailover is a compatibility facade over LeaderRouter; there is one authoritative leader runtime.
- Leader health-check configuration is derived from the registry.
- Groq worker health-check configuration is derived from the registry.
- Generated profile files are not routing authorities and the generator scripts `leader_profiles.py` and `worker_profiles.py` are retired.
- Legacy leader discovery artifacts `discover_leader_models.py` and `leader_capabilities.json` remain preserved only as intentional local pending deletions; do not overwrite or discard that local work.
- Registry-driven router tests exist in `test_registry_routers.py`.
- Runtime connection resilience policy is documented in `RUNTIME_CONNECTION_RESILIENCE.md`.
- WorkerRouter provides a compatibility alias `reset_runtime()` for legacy callers while `reset_runtime_state()` remains the underlying implementation.

## Local validation results

Environment:

- Python: `3.12.10`
- `python -m compileall -q .`: PASS
- `python config_registry.py`: VALID
- `python -m pytest -q test_config_registry.py test_registry_routers.py`: `9 passed`
- `python leader_router.py`: registry synthetic test PASS
- `python worker_router.py`: registry synthetic test PASS
- `python leader_health_check.py`: completed successfully with 11 configured connections
- `python groq_worker_health_check.py`: completed successfully with 15 configured workers
- `python -m compileall -q worker_router.py orchestration_smoke_test.py`: PASS
- `python orchestration_smoke_test.py`: PASS

Final orchestration smoke result observed locally:

```text
Healthy Ultra leaders : 8
Healthy Super leaders : 10
Configured Groq workers: 15

Leader connection : OR-02
Leader model      : nvidia/nemotron-3-ultra-550b-a55b:free
Leader tier       : ULTRA
Leader attempts   : 1
Leader response   : successful
Leader output validation PASSED

Worker connection : GROQ-01
Worker model      : openai/gpt-oss-120b
Standby used      : False
Worker attempts   : 1
Worker response   : successful
Worker output validation PASSED

ORCHESTRATION SMOKE TEST PASSED
Leader -> Worker -> Validation
Runtime failures -> alternate connection/model
Project files sent : NO
```

## Health variability observation

Repeated OpenRouter health checks showed that individual account/model outcomes can vary between runs. Examples included accounts that failed with `INVALID_RESPONSE` on one run and later succeeded, while other accounts changed status between runs.

This is evidence that a health snapshot is time-dependent and must not be treated as permanent account failure. Runtime selection should continue to rely on current validated responses, retry/failover behavior, and runtime failure tracking.

The observed health results are operational evidence only; they do not justify declaring any account permanently unusable from a single transient `INVALID_RESPONSE` result.

## Important synchronization state

Protected local secret files remain outside repository synchronization control and were verified present during this checkpoint:

```text
groq_keys.txt
openrouter_keys.txt
groq_keys.backup.txt
openrouter_keys.backup.txt
```

Local generated profile copies remain preserved outside the repository at the protected local backup location created during branch synchronization. They must not be deleted merely because they are absent from Git.

## Local working tree state

The local working tree still contains these intentional staged deletions from the pre-migration cleanup:

```text
D  discover_leader_models.py
D  leader_capabilities.json
```

Do not discard, reset, or overwrite them without a deliberate decision after dependency review.

## Promotion status

The registry/router/orchestration migration is now operationally validated through the smoke test, but the branch is **not yet promoted to `main`**.

Before promotion:

```text
verified smoke
    ↓
full regression
    ↓
dependency / architecture review
    ↓
update AI_AGENT_HANDOFF.md with verified checkpoint
    ↓
merge/promote to main
```

## Next exact action

Run the broader repository regression suite on the validated branch, then inspect the complete diff for stale profile dependencies, hardcoded pool-size assumptions, and any remaining runtime-state/schema incompatibilities.

Do not reintroduce generated profile files as routing sources.

## Source of truth

Static routing configuration:

`config/registry.json`

Registry loader/validator:

`config_registry.py`

Runtime health/state:

local runtime data only

Generated profiles must not become a second source of routing truth.
