# Baseline Review Notes

## Temporary review repository
`badeemorse961-lang/ai-agent-review`

## Existing building blocks found
The repository contains components for:
- connection registry/fingerprints
- leader model discovery
- leader health checking
- model-aware failover
- worker health checks
- worker routing/leases
- workspace guarding
- execution checkpoint/rollback
- project scanning
- automatic project-state classification
- orchestration smoke testing

## Current leadership design
- OpenRouter / Nemotron Ultra primary
- OpenRouter / Nemotron Super failover

## Findings
### Fixed-size assumptions
`finalize_roles.py` contains a fixed leader count and fixed role slices.
`worker_profiles.py` contains a fixed Groq worker count.

These are genuine N-driven candidates.

### Legacy implementation
`agent.py` is an earlier experimental implementation and still references the removed local Qwen model and hardcoded project paths/files. It must not be treated as the final authoritative agent.

### Multiple role-generation paths
`assign_roles.py`, `role_manager.py`, and `finalize_roles.py` represent different generations of role configuration. The final architecture should have one authoritative role/configuration pipeline.

### Repository hygiene
Checkpoint/history and runtime/test artifacts are currently mixed into the repository snapshot. Final policy must distinguish source, tests, configuration, generated artifacts, and local-only state.

## Next implementation phases
1. Adopt and validate these rules locally.
2. Normalize role/pool configuration to N-driven semantics.
3. Establish repository/local synchronization.
4. Implement specification analysis.
5. Implement current-state analysis.
6. Implement gap/compliance analysis.
7. Build context composition.
8. Integrate the central leader.
9. Integrate specialist orchestration.

These documents define the intended baseline. They do not by themselves prove every current source file already satisfies it.
