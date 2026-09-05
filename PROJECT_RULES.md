# Project Rules

1. Model output is untrusted input.
2. Registry configuration is authoritative for routing and pools.
3. Runtime health/state is local runtime data and must not become static routing truth.
4. All filesystem mutation must remain inside the active project workspace.
5. Independent validation must precede mutation approval.
6. Execution authorization is an internal machine-checked policy decision; normal development must not require human confirmation for each operation.
7. The Execution Gate remains the mutation authority.
8. Checkpoints must precede mutation and rollback must be independently verified.
9. Unknown or unresolved-conflict states are SAFE_STOP conditions.
10. Secrets and credentials must remain outside source control and must never be exposed in logs.
