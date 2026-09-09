# Connection and Pool Rules

## Fundamental model
A connection has:
- stable ID
- provider
- secret fingerprint, never the secret
- health state
- runtime state

Role and pool membership are routing configuration, not connection metadata. The authoritative assignment source is `config/registry.json`.

`connections.json` is connection metadata only. Its `role_source` marker must remain `config/registry.json`; it must never point to a legacy role file or become an independent role authority.

## External provider secret sources

Provider API keys are supplied by the operator through external TXT sources. These files are secret sources only; they are not routing configuration and are never committed to Git.

The single source definition is in `connection_manager.PROVIDER_FILES` and `connection_manager.secret_dir()`:

```text
Base directory:
%LOCALAPPDATA%\AI-Agent\secrets

Groq:
%LOCALAPPDATA%\AI-Agent\secrets\groq_keys.txt

OpenRouter:
%LOCALAPPDATA%\AI-Agent\secrets\openrouter_keys.txt
```

`AI_AGENT_SECRET_DIR` may override the base directory when explicitly configured. Repository-relative fallback remains opt-in only through `AI_AGENT_ALLOW_LEGACY_SECRET_PATH`; production startup sync does not enable it.

Canonical operator format is one API key per non-empty line. Leading/trailing whitespace is trimmed. Blank/comment lines are ignored. A candidate containing internal whitespace is rejected as malformed without exposing its value. Provider-specific validity is not inferred from string shape; provider health/capability validation remains a separate readiness concern.

Startup synchronization is additive and idempotent:

```text
external TXT source
    ↓
parse + deterministic normalization
    ↓
SHA-256 fingerprint
    ↓
compare against existing connection metadata
    ↓
new fingerprint → new stable connection ID
known fingerprint → no duplicate
missing TXT line → no deletion
```

Raw API keys are held only in memory while being processed or used for provider transport. They are not persisted to `connections.json`, `config/registry.json`, diagnostics, benchmark artifacts, or UI state. Connection metadata persists only the provider, stable ID, SHA-256 fingerprint, lifecycle status, and active flag.

When a new connection is discovered but no authoritative registry assignment exists, it is recorded as `PENDING_ASSIGNMENT` and remains inactive. Startup sync never guesses a model, role, pool, or routing policy. This preserves `config/registry.json` as the sole routing authority.

A missing source file is a non-fatal startup condition and is reported as `source_exists=false`; the sync does not create secrets or fall back into the repository.

## N-driven pools
Every pool is logically:

```text
Pool = N connections
```

Do not encode capacity as production constants such as `range(11)`, `len(pool) == 11`, or `len(connections) != 15` when they represent pool capacity.

Use actual configured collection size.

## Connection IDs
IDs are data. `OR-01` and `GROQ-01` are valid identifiers, but routing cannot depend on where numbering ends.

The authoritative registry must assign every routing-eligible connection to exactly one leader pool or worker role, with no duplicate assignment or leader/worker overlap. Pending external imports are explicitly non-routing and are not treated as an assignment.

## Leadership
Primary: Nemotron Ultra.
Failover: Nemotron Super.
Primary exhaustion → failover → full exhaustion → SAFE_STOP.

## Health
Each connection has independent health. Failed connections must be excluded from normal selection and must not be retried indefinitely as healthy.

Health is runtime state and never becomes routing configuration truth.

## Key rotation
Rotate the secret and fingerprint/state while preserving the connection ID and historical identity.

## Expansion
Adding connections requires:
1. add local secret
2. stable ID
3. model capability discovery
4. health validation
5. pool registration
6. regression validation

No routing rewrite.

## Dynamic onboarding status

Automatic source discovery and idempotent connection metadata admission are now implemented at the connection-manager boundary. Full automatic routing assignment remains intentionally gated by an explicit authoritative policy because the current `config/registry.json` does not define a deterministic new-connection role classification rule.

The safe lifecycle is therefore:

```text
new external key
    ↓
connection metadata + fingerprint
    ↓
PENDING_ASSIGNMENT
    ↓
explicit authoritative registry assignment
    ↓
health/readiness validation
    ↓
router eligibility
```

No startup path creates a second registry, routing authority, or secret store.

## Quotas
Use multiple legitimate connections only within provider terms and configured policy. The system must not implement rotation as a quota-evasion mechanism.

## Assignment
Role assignment must be based on the authoritative configured pools in `config/registry.json`, never a fixed global count or a legacy generated role file.
