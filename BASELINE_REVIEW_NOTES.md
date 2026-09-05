# Baseline Review Notes

This document records the known cleanup findings and the intended direction for the repository baseline.

## Immediate cleanup targets

- Remove legacy agent implementation that is not part of the target architecture.
- Remove competing role-generation scripts so there is one authoritative configuration path.
- Remove generated runtime state, health snapshots, result files, backups, and execution checkpoints from source control.
- Keep validated core components available for refactoring rather than deleting working subsystems prematurely.

## Configuration authority

The repository must converge on a single configuration authority for provider connections, model definitions, pools, roles, and policies. Runtime state and health observations must not become configuration truth.

## Current known risks

- `connections.json` contains stale role assignments and must not be treated as the authoritative role registry.
- `finalize_roles.py` contains fixed-size assumptions and should not remain an independent writer of role assignments.
- `worker_profiles.py` contains fixed connection-count assumptions and must become configuration-driven.
- `connection_manager.py` still expects repository-relative secret files; production configuration must locate secrets outside the repository.
- `leader_profiles.py` and the routing layers should consume centralized configuration rather than duplicate model/pool facts.

## Cleanup principle

Delete only clearly obsolete or conflicting artifacts first. Preserve validated execution, scanning, classification, routing, and safety components until their dependencies are mapped and migrated to the authoritative configuration layer.
