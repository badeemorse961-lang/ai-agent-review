# OpenHands Milestone Packet — Professional Desktop Control Center

## Status

**Authorized by Central Leader:** yes

**Milestone:** Professional Desktop Control Center

**Purpose:** Implement the first production-facing Windows desktop application boundary over the already-verified AI-Agent Core without duplicating orchestration, policy, validation, execution authorization, or Git mutation authority.

## Authority

The authoritative sources for this milestone are:

- `AI_AGENT_HANDOFF.md`
- `CURRENT_CHECKPOINT.md`
- `ARCHITECTURE.md`
- `PRODUCT_UI_SPEC.md`
- `PROJECT_RULES.md`
- `SECURITY_AND_EXECUTION_RULES.md`
- `GIT_MUTATION_CONTROL_PLANE.md`
- `OPENHANDS_DEVELOPMENT_ASSISTANT.md`

This packet does not override those sources. It narrows the next implementation scope only.

## Current baseline

The Core is already verified through the existing promoted milestones and current Windows evidence. `CURRENT_CHECKPOINT.md` identifies the Desktop Control Center as the closest real project-level acceptance gate. The Worker work-product protocol remains a separate specification gap and must not be invented as part of the UI milestone.

## Objective

Create a real, maintainable Windows desktop Control Center that exposes the existing Core through a thin typed application/service boundary.

The desktop application must:

1. present authoritative Core/runtime state;
2. capture structured user intent;
3. send bounded requests through Core-owned interfaces;
4. render plans, tasks, evidence, tests, safety stops, and Git state;
5. never become an alternative orchestration or mutation authority;
6. remain independently testable;
7. support a real Windows acceptance path without requiring PowerShell for normal end-user operation.

## Explicit non-goals

Do **not**:

- redesign the existing Core architecture;
- reimplement leader/worker routing in the UI;
- create a second policy engine;
- add a second execution path;
- bypass validation or execution authorization;
- expose unrestricted shell or Git controls;
- persist provider secrets in project files;
- invent a Worker work-product protocol;
- implement dynamic connection onboarding unless already supported by an authoritative Core API;
- replace verified architecture with a new framework merely for visual convenience;
- perform unrelated refactors.

## Required first phase

Before implementing UI screens, inspect the repository for existing callable Core boundaries, adapters, contracts, models, and tests that can safely support the application layer.

Produce an implementation map identifying:

- existing Core entry points suitable for UI use;
- existing state/read models that should be projected into UI read models;
- existing typed request/response contracts;
- existing project/workspace boundaries;
- existing health/runtime/provider state sources;
- existing evidence sources;
- existing safe-stop and authorization state sources;
- tests that can be reused;
- new contracts that are genuinely required for the UI boundary.

If an authoritative Core boundary does not exist, mark the item **OPEN/UNKNOWN** rather than inventing a parallel authority. In that case, stop and report the dependency before implementation.

## Initial implementation slice

The first implementation slice should establish the application boundary and a minimal vertical path, not all screens at once.

Target slice:

```text
Desktop Shell
  -> typed UI/application service
  -> authoritative Core read state
  -> authoritative Core intent entry point (when one exists)
  -> structured result/evidence projection
  -> UI rendering
```

The first vertical path should cover, at minimum:

- application startup;
- active project/workspace identity;
- project state classification;
- current run status;
- Central Leader interaction boundary using structured requests;
- basic plan/task visibility;
- evidence/status rendering;
- safe error and SAFE_STOP rendering;
- no-secret logging/display guarantees.

Do not claim the full UI milestone complete after this slice.

## UI screens required by the authoritative specification

The eventual milestone must cover:

- Dashboard
- Chat with Central Leader
- Projects
- Connections & Pools
- Run / Plan
- Workers
- Evidence & Activity
- Git & Changes
- Tests & Verification
- Safety & Policy Center
- Settings / Diagnostics

Implement them in coherent grouped increments. Prioritize the application boundary and one validated vertical slice before broad screen coverage.

## Technology selection

The implementation technology may be selected using repository constraints and existing tooling, but the result must provide a professional Windows application experience and remain independently testable.

Do not introduce a large unrelated framework migration solely for the UI.

## Security invariants

- Raw provider keys must never be rendered after submission/import.
- Raw keys must never enter chat, telemetry, diagnostics, screenshots, or UI logs.
- UI actions must be typed application intents, not arbitrary shell strings.
- Project paths remain bounded resources.
- Core authorization, validation, sandbox, and mutation policies remain authoritative.
- SAFE_STOP is fail-closed and visible.
- Unrestricted Git operations remain unavailable.
- Diagnostics pass through the existing redaction boundary.

## Testing / evidence requirements

For each implementation slice:

1. syntax/compile checks;
2. focused deterministic tests;
3. UI/application-layer tests;
4. relevant Core regression tests;
5. repository security audit when applicable;
6. `git diff --check`;
7. diff review against `PRODUCT_UI_SPEC.md` and authority boundaries;
8. real Windows validation when the slice is ready for local acceptance.

A visual mockup or successful application launch is not enough.

## Git / mutation rules

OpenHands must not use unrestricted terminal Git mutation as an implementation shortcut. Repository changes remain subject to the project's Git mutation control plane and validation/authorization rules.

Do not clean, reset, rebase, merge, rewrite history, or discard pre-existing working-tree changes.

## Completion contract for each task

Return a structured report containing:

- task identity;
- files changed;
- exact user-facing behavior implemented;
- Core boundaries used;
- tests run and exact outcomes;
- security/redaction checks;
- known limitations;
- evidence paths/artifacts;
- whether any pre-existing change was touched;
- recommended next task.

## SAFE_STOP conditions

Stop without implementation if:

- required Core boundary is absent or ambiguous;
- authoritative documents conflict;
- the implementation would require inventing Worker work-product semantics;
- credentials or secrets would need to enter logs/UI state;
- the proposed UI path would bypass Core authorization or mutation policy;
- existing pre-existing working-tree changes would be overwritten or discarded;
- the acceptance criteria cannot be evidenced.

## First execution instruction

Begin with reconnaissance of the UI application boundary and existing Core APIs/contracts only. Do not start by building the Dashboard mockup. Establish the smallest justified vertical slice from authoritative Core state to Windows UI first.
