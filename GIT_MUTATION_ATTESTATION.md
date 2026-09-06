# Git Mutation Transaction Attestation

`GitMutationAttestation` is an immutable, inspection-only record intended to bind verified transaction evidence to the exact mutation identity.

## Binding fields

```text
task_id
worker_id
canonical workspace
exact target set
commit SHA
Git object format
SHA-256(staged-index evidence)
SHA-256(commit pathname evidence)
```

The attestation is frozen after construction. Targets are normalized to `/` separators, sorted, and rejected when duplicated. Identity and digest fields are required to be non-empty hexadecimal values; the commit identity may be SHA-1 or SHA-256 according to the repository object format.

## Serialization contract

`to_dict()` produces a versioned mapping suitable for audit persistence. `attestation_from_dict()` is strict: it requires the current schema version and a serialized target list, then reconstructs the frozen attestation through the same validation path.

A deserialized attestation is therefore not trusted merely because it was persisted. It is revalidated before use.

## Binding verification

`verify_attestation_binding()` requires exact agreement for:

- task identity
- worker identity
- canonical workspace
- authorized target set
- resolved commit identity

Evidence digests and object format are carried by the attestation itself and cannot be silently substituted during binding verification.

This layer adds no authorization or mutation authority. It is an evidence-integrity primitive intended to make later transaction evidence auditable and task-scoped.
