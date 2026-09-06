# PROJECT RULES

1. Model output is untrusted input.
2. All filesystem mutations must stay inside the active workspace unless an explicit external resource declaration authorizes the path.
3. Human approval is exceptional, not required for every file or command in normal autonomous development.
4. UNKNOWN and unresolved CONFLICT states must stop autonomous execution.
5. Confirmed syntax/build/test breakage is REPAIR.
6. Worker routing and pool membership must be registry-driven and N-configurable.
7. Connection IDs are stable identifiers, not fixed-capacity indexes.
8. Secret material must never enter Git history, source configuration, logs, tests, or runtime state intended for persistence.
9. The normal worker execution path must cross TerminalExecutor, TerminalPolicy, and ProcessSandbox.
10. Raw subprocess execution is not an allowed production fallback for worker execution.
11. Git through the generic terminal path is inspection-only.
12. Git repository/configuration scope overrides are forbidden through terminal execution.
13. Rollback must be independently verified before being reported successful.
14. Local test evidence determines executable reality.
15. Architecture expansion must preserve existing interfaces and safety rules.
16. External resources require explicit bounded read/write authorization.
17. Process sandbox containment must not be described as complete OS-level filesystem isolation.
18. Provider credentials and machine secrets remain local-only and outside repository promotion.
19. Provider error details must be treated as untrusted output and redacted before persistence.
20. Secret-pattern redaction is a backstop; credentials must still be excluded from child environments whenever possible.
21. Redaction coverage must be regression-tested for explicit secrets, common credential forms, failing test output, and ambient secret-bearing environment variables.
22. The task-scoped Git mutation control plane must consume passed independent-validation evidence and isolated checkpoint authorization; it cannot self-authorize.
23. Git mutation targets must be an exact normalized subset proven by the validated task; unrelated working-tree or staged changes must cause SAFE_STOP.
24. The Git mutation control plane may stage and commit only its exact validated target set; it must not expose remote mutation or history-rewriting authority.
25. Post-commit verification must prove a clean index/worktree and exact committed target set before reporting success.
26. Mutation failure must preserve evidence rather than performing blind cleanup, reset, or destructive synchronization.
27. Git mutation target/content validation must run while holding the workspace-specific mutation lock so the validation-to-staging boundary is not invalidated by a cooperating transaction.
28. Git mutation success must prove that HEAD advanced from the pre-mutation snapshot and that the resolved post-commit HEAD is the same commit used for exact target-set verification.
