# Git Mutation Transaction Attestation

`GitMutationAttestation` is an inspection-only evidence object for a completed task-scoped Git transaction.

## Binding contract

An attestation binds together:

```text
task_id
worker_id
canonical workspace
exact authorized targets
commit identity
Git object format
staged evidence digest
commit pathname evidence digest
```

The object is frozen after construction and normalizes target ordering. Target duplicates, unsupported object formats, malformed identities, and invalid digest lengths fail closed.

## Serialization contract

`to_dict()` emits a versioned mapping with `schema_version`. `attestation_from_dict()` requires the exact supported schema version and a serialized target list before reconstructing the immutable object.

The serialization format is intentionally strict so evidence cannot silently downgrade or reinterpret a future schema.

## Binding verification

`verify_attestation_binding()` reconstructs the expected identity binding from the active transaction context and requires exact equality for task, worker, canonical workspace, targets, and commit identity. Evidence digest values and object format are preserved from the attestation and remain part of the immutable binding.

This component does not authorize, stage, commit, reset, push, or otherwise mutate a repository. It exists to make already-verified transaction evidence portable and auditable before any later consumer uses it.
