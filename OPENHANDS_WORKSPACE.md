# OpenHands Workspace Contract

## Purpose

This file defines the safe filesystem boundary used when OpenHands is attached to this repository.

## Rules

- The primary development checkout remains `D:\AI-Agent\Sandbox\agent-test`.
- OpenHands must not use the primary checkout as its first mutation target.
- Real OpenHands work must use a dedicated working copy/branch derived from the authoritative repository state.
- The OpenHands Docker mount must map only that dedicated working copy to `/projects`.
- Do not mount `D:\AI-Agent\Sandbox`, the whole `D:\AI-Agent`, or any parent directory that contains unrelated projects, credentials, backups, or machine state.
- Keep `.git` available when repository inspection is required, but do not grant broader filesystem access through additional mounts.
- If an external path is genuinely required, it must be declared and bounded by the project resource-authority rules before use.
- If the workspace boundary cannot be proven, stop with `SAFE_STOP`.

## Current validated test mapping

```text
D:\AI-Agent\Sandbox\openhands-test  ->  /projects
```

The mapping above was validated by an actual file-creation test. It is a test environment, not the production project workspace.

## Intended project mapping

For the next real intake, create a dedicated local working copy under:

```text
D:\AI-Agent\Sandbox\openhands-ai-agent-review
```

and mount only that directory:

```text
D:\AI-Agent\Sandbox\openhands-ai-agent-review  ->  /projects
```

OpenHands must begin with read/evidence work only according to `OPENHANDS_FIRST_ENGAGEMENT.md`.
