# CURRENT CHECKPOINT

## Status
Registry-driven router migration has been implemented on the working branch:

`agent/registry-router-migration`

## Completed in this checkpoint

- LeaderRouter now derives provider, models, and leader pools from `config/registry.json`.
- WorkerRouter now derives provider, model, and role pools from `config/registry.json`.
- Worker runtime failures are tracked separately from external health so a refresh does not erase runtime failures.
- LeaderFailover is now a compatibility facade over LeaderRouter; there is one authoritative leader runtime.
- Leader health-check configuration is derived from the registry.
- Groq worker health-check configuration is derived from the registry.
- Generated profile generator scripts `leader_profiles.py` and `worker_profiles.py` are retired.
- Legacy leader discovery artifacts were already retired: `discover_leader_models.py` and `leader_capabilities.json`.
- Registry-driven router tests exist in `test_registry_routers.py`.

## Important validation status

The registry itself was previously verified:

- leader provider: OpenRouter
- primary accounts: 11
- failover accounts: 11
- worker provider: Groq
- worker roles: 6
- worker accounts: 15
- registry tests: 4/4 PASS

The newly migrated router/health-check code has **not yet been executed locally after these changes**.

Do not claim this migration is operationally verified until the local validation checkpoint below passes.

## Next action: LOCAL VALIDATION CHECKPOINT

Bring this branch to the local machine and run:

1. syntax/compile validation for the changed Python files;
2. `python config_registry.py`;
3. `python -m unittest -v test_config_registry.py`;
4. `python -m unittest -v test_registry_routers.py`;
5. `python leader_router.py` synthetic test;
6. `python worker_router.py` synthetic test;
7. `python leader_failover.py` compatibility check;
8. orchestration smoke test after dependency compatibility is confirmed.

If any test fails, stop, preserve the failure evidence, classify the failure, and repair on this branch before promoting it.

## Promotion rule

Do not merge this branch into `main` until the local validation checkpoint passes.

After successful validation:

```text
validated branch
    ↓
review diff
    ↓
update AI_AGENT_HANDOFF.md with verified checkpoint
    ↓
merge/promote to main
    ↓
pull main to local
```

## Source of truth

Static routing configuration:

`config/registry.json`

Registry loader/validator:

`config_registry.py`

Runtime health/state:

local runtime data only

Generated profiles must not become a second source of routing truth.
