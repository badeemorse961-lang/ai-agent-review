# Connection and Pool Rules

## Fundamental model
A connection has:
- stable ID
- provider
- secret fingerprint, never the secret
- lifecycle state
- runtime health/state

Role and pool membership are routing configuration, not connection metadata. The authoritative assignment source is `config/registry.json`.

`connections.json` is metadata-only. It contains stable identity, provider, fingerprint, lifecycle metadata, and role-source marker; it never stores raw provider secrets.

## Credential storage layers
The credential lifecycle is intentionally separated:

```text
TXT import source
    ↓ parse / validate / fingerprint
Windows Protected Local Secret Store (user-scoped DPAPI)
    +
connections.json metadata
    +
config/registry.json routing authority
```

TXT files are import sources only. They are not the credential source of truth after import, and omission from a later TXT file never deletes or disables an existing connection.

Production Windows persistence uses the current user's Windows DPAPI-backed protected store. Runtime resolves a credential by stable connection ID only when a provider transport request needs it.

## Import semantics
TXT import is **ADDITIVE**:
- new fingerprints are added;
- existing fingerprints are counted as already present and remain idempotent;
- duplicate imports do not create new connection IDs;
- existing connections not present in the import file remain unchanged;
- malformed or rejected source lines are reported without exposing the secret;
- the import result reports imported, already-present, rejected, and persistence status.

An import operation has no stale/removal pass.

## Connection lifecycle
Every connection uses one of:

```text
ACTIVE
DISABLED
FAILED
INVALID
REMOVED
```

`DISABLED`, `FAILED`, `INVALID`, and `REMOVED` are excluded from effective router eligibility. FAILED/INVALID preserves the protected credential and metadata until an explicit disable or remove action.

`Enable` is allowed only for a connection that still exists in the protected store and is explicitly assigned by the authoritative `config/registry.json`. Dynamic auto-assignment is intentionally not performed by this milestone.

`Remove` requires explicit UI confirmation, deletes the credential from protected storage, removes the connection from the authoritative assignment pools when present, and leaves a metadata tombstone with `REMOVED` state. Other connections are not changed.

## N-driven pools
Every pool is logically:

```text
Pool = N connections
```

Do not encode capacity as production constants such as `range(11)`, `len(pool) == 11`, or `len(connections) != 15` when they represent pool capacity.

Use actual configured collection size.

## Connection IDs
IDs are data. `OR-01` and `GROQ-01` are valid identifiers, but routing cannot depend on where numbering ends.

The authoritative registry must assign every **eligible** connection to exactly one leader pool or worker role, with no duplicate assignment or leader/worker overlap. Imported disabled/quarantined metadata may remain unassigned until explicitly admitted by configuration.

## Leadership
Primary: Nemotron Ultra.
Failover: Nemotron Super.
Primary exhaustion → failover → full exhaustion → SAFE_STOP.

## Health
Each connection has independent health. Failed connections must be excluded from normal selection and must not be retried indefinitely as healthy.

Health is runtime state and never becomes routing configuration truth.

## Key rotation
Rotate the protected secret and fingerprint/state while preserving the connection ID and historical identity.

## Expansion
Adding connections requires:
1. add/import local secret
2. stable ID
3. model capability discovery
4. health validation
5. explicit pool registration
6. regression validation

No automatic routing rewrite is performed by this milestone.

## Future operational requirement: Dynamic Connection Onboarding & Auto-Assignment

This remains a **future readiness requirement**, not a current implementation milestone.

The current status is still:

**CONFIGURATION-DRIVEN ONLY**.

Automatic capability discovery, deterministic classification, service-side pool insertion without manual registry editing, onboarding health admission, and automatic quarantine/re-admission are not claimed by this milestone.

## Quotas
Use multiple legitimate connections only within provider terms and configured policy. The system must not implement rotation as a quota-evasion mechanism.

## Assignment
Role assignment must be based on the authoritative configured pools in `config/registry.json`, never a fixed global count or a legacy generated role file.
