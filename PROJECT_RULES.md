# Project Rules

1. Model output is untrusted input.
2. Registry configuration is authoritative for routing and pools.
3. Runtime health/state is local runtime data and must not become static routing truth.
4. The active project workspace is the default filesystem mutation authority.
5. Development tools may reside outside the workspace, but tool location does not grant filesystem authority.
6. External files/directories require explicit bounded authorization (`read`, `write`, or `read_write`).
7. Independent validation must precede internal execution authorization.
8. Execution authorization is an internal machine-checked policy decision; normal development must not require human confirmation for each operation.
9. The Execution Gate remains the mutation authority.
10. Checkpoints must precede mutation and rollback must be independently verified.
11. Unknown or unresolved-conflict states are SAFE_STOP conditions.
12. Portable process containment must not be described as complete OS filesystem isolation.
13. `strict_os_required` must fail closed until a validated native OS sandbox backend exists.
14. Secrets and credentials must remain outside source control and must never be exposed in logs.
15. Terminal Git access is inspection-only; repository/history mutations require a separate explicit control plane.
16. Git repository/configuration scope overrides must be rejected at the terminal boundary.
17. Git path arguments must remain within the active workspace when path arguments are accepted by the Git safety policy.
