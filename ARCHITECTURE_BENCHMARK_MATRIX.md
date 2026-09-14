ARCHITECTURE BENCHMARK MATRIX
Baseline: f3e1423 (credential live rebind complete).
Only files changed from baseline: credential_pool_manager.py, tests/ui/test_credential_reload_readonly.py (credential milestone verified).
New file: ARCHITECTURE_BENCHMARK_MATRIX.md (benchmark only).
Core remains sole authority. No Batch 4 started. No desktop UI implemented. No architecture contradiction found.

CAPABILITY GROUPS (18):
1. THIN UI/API BOUNDARY -> ADAPT (adapter/service; no second authority; deferred)
2. TASK CONTRACT -> ADAPT (WorkerWorkProduct preserved; first Contract Consolidation batch)
3. TASKGRAPH/DAG -> ADAPT/DEFER (current pipeline sufficient; independent)
4. STRUCTURED ARTIFACTS -> ADAPT (extension of existing evidence; second batch)
5. WORKERWORKPRODUCT -> ADOPT / PRESERVE (authoritative; f3e1423 verified; no replacement)
6. VALIDATION/REVIEWER -> ADOPT / PRESERVE (existing; no duplicate)
7. FAILURE CLASSIFICATION -> ADOPT / PRESERVE (REPAIR/UNKNOWN/CONFLICT preserved)
8. PROVIDER GATEWAY -> ADAPT (use existing connection_manager; adapter over authority; deferred)
9. PROVIDER/ACCOUNT -> ADAPT (map to existing pool/credential authority; independent)
10. RUNTIME EVENTS -> ADAPT/DEFER (conceptual; adapter; benefits artifacts; deferred)
11. STATE PROJECTION -> ADAPT (DesktopProjection read-only adapter; uses same contracts; independent)
12. WORKTREE ISOLATION -> ADOPT / PRESERVE (existing mutation lock + sequence guard sufficient)
13. CAPABILITY-BASED EXECUTION -> ADOPT / PRESERVE (execution authority capability-based; preserved)
14. EXECUTION LOCKS/CLAIMS -> ADOPT / PRESERVE (mutation lock + sequence guard verified at f3e1423)
15. FLEET/RUNTIME STATE -> ADAPT (pool concepts sufficient; independent; deferred)
16. RECOVERY/FAILOVER -> ADOPT / PRESERVE (failover/reload/recovery verified; deferred structured contract)
17. EVIDENCE FLOW -> ADOPT / PRESERVE (evidence core; structured contract deferred; no second authority)
18. DESKTOP CONTROL CENTER -> ADAPT / DEFER (adapter/service; requires Contract Consolidation first; desktop UI not started; Batch 4 not started; milestone complete)

RECOMMENDED FIRST CONTRACT CONSOLIDATION BATCH:
1. Structured task contract
2. Structured evidence/artifact contract
3. Provider/account abstraction contract
4. State projection / DesktopProjection contract
Desktop UI deferred (post-contract consolidation; requires stable contracts; adapter/service; uses same core contracts; uses same authorization/evidence/contracts; uses same mutation control; requires real desktop acceptance per ARCHITECTURE.md invariant 26).
No architecture contradiction discovered; ARCHITECTURE.md unchanged; IMPLEMENTATION_ROADMAP.md unchanged; no unrelated modifications made.
