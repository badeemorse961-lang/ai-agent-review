# Git Mutation Result Restoration

`git_mutation_result_codec.py` is the trust boundary for restoring a persisted `GitMutationResult` from the local audit record.

## Restoration contract

Restoration is strict and version-aware. The codec validates:

- result schema version
- string, boolean, and list field types
- Git commit identity shape
- SHA-256 digest shape
- snapshot structure and field types
- required attestation presence for verified or committed results
- post-commit `HEAD` equality with the result commit identity
- equality of task, worker, target, and commit identities between the result and attestation
- the attestation's canonical workspace binding through `verify_attestation_binding`

The codec never mutates the workspace, executes Git commands, grants authorization, or repairs malformed state.

## Fail-closed behavior

Malformed or tampered audit data raises `GitMutationResultRestoreError`. The caller must treat restoration failure as untrusted state rather than attempting blind recovery.

The attestation remains evidence, not authority. Successful restoration only proves that the serialized result is internally consistent with its embedded transaction attestation; callers that reuse the evidence must still bind it to the live task context they are authorizing.
