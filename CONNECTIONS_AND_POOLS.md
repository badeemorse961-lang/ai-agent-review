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

## Quotas
Use multiple legitimate connections only within provider terms and configured policy. The system must not implement rotation as a quota-evasion mechanism.

## Assignment
Role assignment must be based on the authoritative configured pools in `config/registry.json`, never a fixed global count or a legacy generated role file.
