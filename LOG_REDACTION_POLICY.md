# Log Redaction and Secret-Leak Prevention

## Purpose

Runtime output, test diagnostics, provider error payloads, and persisted execution state are untrusted data. They must not become a secondary channel for credentials.

## Redaction boundary

Secret sanitization is centralized in `secret_redaction.py` and is applied at the points where output becomes observable or persistent:

```text
child process output
        ↓
ProcessSandbox
        ↓
SecretRedactor
        ↓
ProcessResult / caller
```

Execution Gate test output follows the same rule before it is stored in execution state or returned to callers.

Provider health-check errors are redacted before they are persisted to health JSON.

## Two-layer strategy

1. **Explicit values** — secrets supplied through approved runtime inputs, including allowed `AGENT_*` environment variables, are registered with the redactor and replaced exactly.
2. **Credential patterns** — common bearer tokens, Groq keys (`gsk_...`), OpenRouter keys (`sk-or-v1-...`), generic `sk-...` credentials, and secret-like assignments/query parameters are redacted even when the exact value was not registered.

Pattern matching is a backstop, not a substitute for keeping credentials out of the child environment.

## Environment rule

`ProcessSandbox` already removes credential-bearing ambient environment variables from child processes. Requested environment variables remain narrowly allowlisted; their values are also registered for output redaction.

## Persistence rule

Any stdout/stderr retained in `ProcessResult`, execution-gate state, or health-check JSON must be redacted before persistence. Raw exception text must not be printed without the redaction boundary.

## Testing requirement

Regression tests must demonstrate that:

- an explicit non-standard secret is removed from process output;
- bearer and provider-shaped credentials are removed;
- failing pytest output cannot persist an explicit secret;
- secret-like ambient environment variables are not passed to child processes.

## Non-goal

Redaction does not provide filesystem isolation and does not make arbitrary child processes trustworthy. Secrets should still remain outside source control, outside unmanaged resources, and outside child environments whenever possible.
