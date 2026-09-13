# OpenHands First Engagement Packet

## Purpose

This packet defines the first real task assigned to OpenHands after the isolated environment was validated.

OpenHands is being introduced as a **development assistant for the existing AI-Agent project**. It is not being introduced as a replacement for the Central Leader, the project governance model, the repository rules, or the existing guarded Git mutation path.

## Current project baseline

Repository:
`badeemorse961-lang/ai-agent-review`

Authoritative branch:
`main`

Primary local development checkout:
`D:\AI-Agent\Sandbox\agent-test`

The current project is substantially implemented and must be treated as a CONTINUE/MAINTAIN/REPAIR/UNKNOWN classification problem based on evidence, not as a greenfield build.

The current checkpoint states that the Core architecture, canonical integration, regression/security/runtime integrity, and accepted PR #47 Windows validation are verified. The production runtime end-to-end path remains partially verified because the Worker work-product protocol is not yet defined. The Professional Desktop Control Center is an implementation gap and is the closest major project-level acceptance milestone.

## Required reading before any analysis

OpenHands must read the current authoritative versions of:

```text
AI_AGENT_HANDOFF.md
CURRENT_CHECKPOINT.md
TASK.md
BASELINE_REVIEW_NOTES.md
ARCHITECTURE.md
PROJECT_RULES.md
SECURITY_AND_EXECUTION_RULES.md
GIT_MUTATION_CONTROL_PLANE.md
OPENHANDS_DEVELOPMENT_ASSISTANT.md
PRODUCT_UI_SPEC.md
```

It must then inspect the executable code and tests relevant to the current objective.

Actual repository state, executable evidence, and authoritative specifications override narrative memory.

## First task: evidence-first project intake

**Do not implement a feature in this first engagement.**

The objective is to produce a reliable engineering intake for the Central Leader.

OpenHands must:

1. classify the current repository state as BUILD, CONTINUE, MAINTAIN, REPAIR, CONFLICT, or UNKNOWN;
2. identify the nearest real engineering gap(s) supported by repository evidence;
3. distinguish verified capabilities from partially verified capabilities and specification gaps;
4. inspect the existing Control Center requirements and determine the exact implementation boundary without inventing additional product scope;
5. identify dependencies or blockers for the next grouped milestone;
6. identify the smallest coherent implementation slice that can be prepared next;
7. map the relevant existing modules, tests, specifications, and authority boundaries;
8. state what must remain untouched;
9. propose the validation evidence required before any promotion;
10. stop rather than guess where repository evidence is insufficient.

## Explicit no-change rule

During this intake task:

- do not modify production source files;
- do not modify tests;
- do not modify routing configuration;
- do not add providers or credentials;
- do not change Git policy;
- do not change the execution/sandbox boundaries;
- do not create a parallel orchestration architecture;
- do not commit, push, or alter remote repository history;
- do not broaden filesystem access;
- do not invent a Worker work-product protocol;
- do not replace validated architecture with a preferred alternative.

The task is analysis and evidence collection only.

## Required output

Return an evidence-rich report containing exactly these sections:

### 1. Repository state classification

State the classification and the concrete evidence supporting it.

### 2. Verified baseline

List the major capabilities that are demonstrably present and where the evidence was found.

### 3. Open implementation/specification gaps

List only gaps supported by the repository. Separate implementation gaps from specification/evidence gaps.

### 4. Next grouped milestone candidate

Describe the smallest coherent milestone that advances the project without bypassing existing authority boundaries.

### 5. Impacted surface

List the relevant files/modules/tests/specifications and why each matters.

### 6. Safety and authority boundary

State which existing execution, workspace, Git, secret, validation, and rollback controls must remain authoritative.

### 7. Validation plan

Define the focused tests, regression checks, security/integrity checks, and real Windows acceptance evidence that would be required for the proposed milestone.

### 8. Unknowns / blockers

Record anything that cannot be established from the current repository state.

### 9. Recommendation to the Central Leader

Give one bounded recommendation. Do not authorize implementation yourself.

## Report discipline

The report is evidence, not authority. The Central Leader must independently verify material claims before authorizing implementation or promotion.

If a requested fact cannot be established from the repository, say `UNKNOWN` and identify the missing evidence.

## Success condition

The first engagement succeeds only when the Central Leader can use the report to select the next grouped engineering milestone without reopening the whole project discovery process.
