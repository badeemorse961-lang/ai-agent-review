# Postman API integration

The repository now exposes a small loopback HTTP adapter over the existing `application_boundary.ControlCenterService`.

It is intentionally not a second execution authority:

```text
Postman / HTTP client
        ↓
api_server.py
        ↓
ApplicationIntent
        ↓
ControlCenterService
        ↓
AI-Agent Core
```

The adapter accepts structured application intents only. It does not accept shell commands, raw Core calls, Git mutation commands, or credentials.

## Start locally

From the repository root:

```powershell
python api_server.py --workspace-root . --host 127.0.0.1 --port 8765
```

The default listener is loopback-only. Use a different host only when the deployment policy explicitly allows it.

## Endpoints

- `GET /health` — local process health.
- `GET /api/v1/capabilities` — declared application-intent capabilities.
- `POST /api/v1/intents` — structured intent dispatch through `ControlCenterService`.

The Postman collection deliberately excludes credential-bearing workflows and mutation-capable task execution from the default run set.

## Postman import

Import these two files into Postman:

- `postman/AI-Agent-Control-Center.postman_collection.json`
- `postman/AI-Agent-Control-Center-Local.postman_environment.json`

Set `workspace_root` in the environment to the local project path before using `Select Project`.

Run the collection starting with `Health` and `Capabilities`. Safe read/inspection intents can then be exercised with `Refresh Dashboard`, `Refresh Connections`, `Git Snapshot`, and `Session Evidence`.
