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

## N-driven pools
Every pool is logically:

```text
Pool = N connections
```

Do not encode capacity as production constants such as `range(11)`, `len(pool) == 11`, or `len(connections) != 15` when they represent pool capacity.

Use actual configured collection size.

## Connection IDs
IDs are data. `OR-01` and `GROQ-01` are valid identifiers, but routing cannot depend on where numbering ends.

The authoritative registry must assign every declared connection to exactly one leader pool or worker role, with no duplicate assignment or leader/worker overlap.

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

## Future operational requirement: Dynamic Connection Onboarding & Auto-Assignment

This is a **future readiness requirement**, not a current implementation milestone and not a reason to interrupt the canonical orchestration acceptance gate.

The target operational flow is:

```text
new connection/account
    ↓
validate provider + model + metadata
    ↓
validated capability discovery
    ↓
deterministic policy/registry assignment
    ↓
register in exactly one eligible pool/role
    ↓
health check
    ↓
eligible for router selection
    ↓
automatic quarantine/removal from effective availability on invalidation/failure
```

The target behavior must remain compatible with these authority rules:
- `config/registry.json` remains the routing authority;
- pool capacity is N-driven and never represented by hard-coded Python counts;
- connection IDs are unique and stable;
- each connection belongs to exactly one valid assignment;
- provider, model, and role assignments must be policy-consistent;
- runtime health/state is observation data and never becomes configuration authority;
- secrets remain outside Git and normal persisted runtime evidence.

### Current status assessment

**CONFIGURATION-DRIVEN ONLY**.

The current implementation already supports registry-defined leader/worker pools, N-driven pool sizes, uniqueness and assignment validation, provider/role consistency checks, runtime health separation, and router exclusion of unavailable connections. These capabilities support expansion by configuration, but they do **not** constitute automatic onboarding.

Automatic capability discovery, deterministic classification of a newly introduced connection, service-side pool insertion without manual registry editing, onboarding health admission, and automatic quarantine/re-admission lifecycle are not currently established as a verified end-to-end behavior.

Do not mark this requirement as `AUTO-ONBOARDING VERIFIED` merely because the registry accepts additional connection IDs or because the routers consume variable-length configured pools.

## Quotas
Use multiple legitimate connections only within provider terms and configured policy. The system must not implement rotation as a quota-evasion mechanism.

## Assignment
Role assignment must be based on the authoritative configured pools in `config/registry.json`, never a fixed global count or a legacy generated role file.
