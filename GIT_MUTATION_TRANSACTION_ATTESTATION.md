# Git Mutation Transaction Attestation

`GitMutationAttestation` is an immutable inspection record attached to a successful `GitMutationResult`.

It is created only after the authoritative transaction has already passed its existing authorization, policy, staging, staged-content, commit, clean-state, HEAD, and committed-target evidence checks.

## Binding contract

The attestation binds:

- `task_id`
- `worker_id`
- canonical workspace path
- exact normalized authorized target set
- committed Git object identity
- Git object format (`sha1` or `sha256`)
- SHA-256 digest of the exact trusted staged-index evidence stdout
- SHA-256 digest of the exact trusted post-commit pathname evidence stdout

The attestation is frozen after construction. Serialized data is versioned and revalidated before restoration.

## Trust boundary

The attestation does not grant authorization and cannot perform Git or filesystem mutation. It records evidence already accepted by existing boundaries.

A restored attestation must be rebound to the same task, worker, canonical workspace, exact targets, and commit identity before it is accepted for later use.

## Failure behavior

The contract fails closed for schema drift, malformed hexadecimal fields, invalid identity lengths, unsupported object formats, duplicate targets, target-shape drift, or identity binding drift.

Audit persistence stores the attestation as part of the successful mutation result. The commit message remains represented only by its SHA-256 digest and is not copied into the audit record.
