# Git Mutation Live Evidence Rebinding

`git_mutation_live_rebind.py` provides the inspection-only boundary for reusing a persisted `GitMutationResult` after it has been restored from audit state.

## Rebinding contract

A result is accepted only when all of the following remain true in the active workspace:

- the restored result and its embedded transaction attestation are internally consistent;
- the process sandbox is bound to the same canonical workspace;
- the active branch matches the post-commit branch recorded by the result;
- the current `HEAD` matches the attested commit identity;
- the current index and working tree are clean;
- `git show --format= --name-only -z <commit>` still proves the exact result target set;
- the SHA-256 digest of that live committed-target evidence equals the attested post-commit evidence digest.

All Git reads are executed through the existing `ProcessSandbox` with an explicitly allowlisted Git executable. No command in this boundary performs mutation.

## Historical versus live evidence

The attestation's staged-index digest remains historical evidence from the pre-commit phase. It is not recomputed after commit because the staged index is intentionally clean at successful transaction completion.

The committed-target evidence is recomputed during rebinding, so later consumers can distinguish an internally consistent audit record from a transaction whose live repository context has drifted.

## Failure behavior

Branch drift, `HEAD` drift, dirty repository state, workspace-policy mismatch, malformed restored data, target-set mismatch, or committed-evidence digest mismatch all fail closed with `GitMutationLiveRebindError`.

The rebind operation does not authorize work, repair state, reset files, switch branches, or perform recovery. A successful rebind is evidence only and must remain subordinate to the caller's current authorization decision.
