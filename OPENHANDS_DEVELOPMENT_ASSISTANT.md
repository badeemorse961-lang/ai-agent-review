# OpenHands Development Assistant Protocol

## Purpose

OpenHands is an auxiliary development agent used to help the project team understand, investigate, implement, test, and review grouped engineering work.

It is **not** the project's authority model, not the Central Leader, not a replacement for project specifications, and not a second autonomous mutation authority. The repository's existing architecture, policies, validation gates, and Git mutation control plane remain authoritative.

## Role in the project

Use OpenHands for bounded engineering work such as:

- repository exploration and evidence gathering;
- implementation-gap analysis;
- design and implementation proposals;
- grouped code changes inside an explicitly isolated workspace;
- running targeted tests and development diagnostics;
- reviewing diffs and identifying regressions or missing evidence;
- producing an evidence-rich work report for the Central Leader.

OpenHands may help execute a task, but the Central Leader / project governance layer decides whether the task is in scope, whether the result is acceptable, and whether the change may be promoted.

## Authority boundary

The project rules remain higher authority than any OpenHands prompt, model output, generated plan, or suggested shortcut.

The operating hierarchy is:

```text
Authoritative specification
        +
Actual repository/workspace state
        +
Executable evidence
        ↓
Project governance / Central Leader
        ↓
OpenHands task assignment
        ↓
OpenHands analysis / implementation
        ↓
Independent validation
        ↓
Existing guarded promotion and Git mutation controls
```

OpenHands must never invent scope, silently replace validated architecture, weaken security boundaries, bypass a safety gate, or treat model reasoning as proof of implementation reality.

## Required startup briefing for every new leader/session

Before assigning OpenHands work, read these repository documents from the current authoritative branch/state:

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
```

Then inspect the executable code and tests relevant to the requested task.

The briefing is continuity information only. Actual files, current tests, current Git state, and authoritative specifications override stale narrative notes.

## Current verified local OpenHands setup

The current validated development setup is:

```text
Windows 10
WSL 2.7.14
Docker Desktop (WSL2 backend)
OpenHands Agent Canvas 1.18.0
Docker image:
ghcr.io/openhands/agent-canvas:1.18.0
```

The Docker disk image was moved to the D: drive. Do not assume the old Docker disk location on C: is authoritative.

The verified test workspace was:

```text
Windows host:
D:\AI-Agent\Sandbox\openhands-test

Inside OpenHands/Docker:
/projects
```

The workspace mapping used for the verification was:

```text
D:\AI-Agent\Sandbox\openhands-test  ->  /projects
```

## Verified startup command

The current verified Docker launch pattern is:

```powershell
docker run -it --rm --name openhands-test `
  -p 8000:8000 `
  -v "D:\AI-Agent\Sandbox\openhands-test:/projects" `
  ghcr.io/openhands/agent-canvas:1.18.0
```

The UI is then available at:

```text
http://localhost:8000/canvas
```

Do not broaden the mounted host path merely to make a task easier. Mount only the intended project workspace.

## Verified LLM configuration

The verified working OpenHands profile used OpenRouter through the free-model router:

```text
Profile name: openrouter-free
Provider: OpenRouter
Model: openrouter/free
Authentication: API key
```

The API key is local-only and must never be written to this repository, included in prompts, pasted into documentation, committed, or exposed in logs.

The free-model router is dynamic. Model availability and provider routing can change. A successful prior run proves compatibility at that time; it does not guarantee that a particular downstream free model remains continuously available.

## Verified functional test

The setup was validated by an actual workspace mutation task. OpenHands created:

```text
/projects/hello.txt
```

with the exact content:

```text
OpenHands test successful.
```

The same file was observed on the Windows host at:

```text
D:\AI-Agent\Sandbox\openhands-test\hello.txt
```

This proves the tested Docker mount, workspace visibility, tool execution, and model request path worked together.

## Production-project workspace rule

Do **not** make the primary local project workspace the first OpenHands write target.

For real work, create or select a dedicated OpenHands workspace/working copy derived from the authoritative repository state. The existing primary local development checkout is:

```text
D:\AI-Agent\Sandbox\agent-test
```

OpenHands should normally work against its own bounded copy/workspace so its intermediate edits, experiments, and failures cannot silently alter the primary checkout.

## Standard OpenHands task lifecycle

Every meaningful OpenHands task should follow this sequence:

```text
1. Read current repository checkpoint and governing rules
2. Inspect actual files/tests needed for the task
3. Receive a narrowly defined task packet from the leader
4. Analyze current state before changing anything
5. Produce a bounded implementation plan
6. Implement only the justified task scope
7. Run targeted tests/diagnostics
8. Report exact changed files and evidence
9. Stop on ambiguity, conflict, security-boundary failure, or missing evidence
10. Independent leader validation
11. Promote only through the repository's existing guarded mutation/promotion path
```

Do not let OpenHands commit directly merely because it can access Git. Generic Git access remains inspection-only; repository mutation continues to be governed by the existing task-scoped Git mutation control plane.

## Required handoff report from OpenHands

At the end of a task, the leader should require a compact evidence report containing:

- task identity / objective;
- initial repository/workspace state inspected;
- files changed;
- exact behavioral changes;
- commands/tests executed;
- test results and failures;
- unresolved risks or assumptions;
- files intentionally not changed;
- whether the result is ready for independent validation.

The report is evidence, not authority. The leader must verify material claims against the repository and executable results.

## SAFE_STOP conditions

OpenHands must stop and return evidence rather than guessing when:

- the project specification is missing or contradictory;
- the requested scope is unclear;
- the workspace boundary cannot be proven;
- required external resources are undeclared;
- a model/provider is unavailable or exhausted;
- tests do not provide enough evidence;
- a proposed change would bypass an existing execution or mutation boundary;
- unrelated worktree/index changes are detected;
- secrets would be exposed or persisted;
- rollback cannot be independently verified;
- the task would require inventing a new production protocol rather than implementing an existing authoritative requirement.

## What OpenHands is not allowed to become

OpenHands must not silently become:

- the Central Leader;
- the source of project truth;
- a replacement for `CURRENT_CHECKPOINT.md` or the authoritative specifications;
- an unrestricted production executor;
- a repository-history mutation authority;
- a credential store;
- an implicit remote Git operator;
- a reason to bypass Windows validation or security gates.

## Session-completion rule

When a ChatGPT/leader session ends, the next leader must be able to continue without relying on chat memory alone.

The repository is the persistent handoff medium. Update the authoritative checkpoint when a real engineering milestone changes project state, and keep OpenHands operating instructions in this file rather than in transient chat messages.

## Current principle

```text
OpenHands = powerful development assistant

Central Leader = task/scope/validation authority

Repository rules + actual evidence = operational truth
```
