ARCHITECTURE HARVEST — EXTRACTED MECHANISMS FROM BENCHMARK PROJECTS
=====================================================================
Baseline: 7ff60db (credential milestone + benchmark matrix committed). Only change from f3e1423: ARCHITECTURE_BENCHMARK_MATRIX.md. Core authority preserved.
Document type: RESEARCH / ARCHITECTURE ONLY — no implementation; no existing contracts modified; no WorkerWorkProduct / IndependentValidator / ExecutionAuthorizationBoundary / ExecutionGate / GitMutationExecutor / credential authority / SecretRedactor replaced.

SOURCE INTEGRITY NOTE
---------------------
External sources: OpenHands SDK docs (docs.openhands.dev); Hivemind project specs / artifact contracts (references in repository context); Coddess patterns (CONNECTIONS_AND_POOLS.md, connection_manager contracts); Control Center / PRODUCT_UI_SPEC.md / ARCHITECTURE.md / provider_transport.py (repository-verified). No external source code copied into repository. Where direct source inspection unavailable, marked OBSERVED-INTERFACE.

A. OPENHANDS — EXTRACTED MECHANISMS
--------------------------------------
A1. API / CLIENT BOUNDARY [OBSERVED-INTERFACE] — Client->Agent Server; typed request/response; workspace owned by server. Verifies UI = adapter over Core (ARCHITECTURE.md invariant 24-26). Verdict: ADAPT (existing adapter/service concept). Existing: ARCHITECTURE.md Application/UI Service Boundary; PRODUCT_UI_SPEC.md. Gap: No typed adapter contract. Security: UI cannot bypass auth/gate; redaction required; no unrestricted shell/Git/remote.
A2. RUNTIME / BACKEND SEPARATION [OBSERVED-INTERFACE] — Server owns mutation/state; agent observes. Confirms Core authority split (workspace/tool/external). Verdict: ADOPT / PRESERVE. Existing: ARCHITECTURE.md resource authority + mutation control + GitMutationExecutor. Gap: None.
A3. TYPED REQUEST / RESPONSE FLOW [OBSERVED-INTERFACE] — Structured intent -> typed response; no arbitrary shell through adapter. Direct model for adapter/service. Verdict: ADAPT (new adapter contract). Existing: None at adapter; core uses fingerprint/status/previous_pool_keys. Gap: No adapter-level typed contract. Security: Must not expose secrets; mutation requires auth evidence.

B. HIVEMIND — EXTRACTED MECHANISMS
-----------------------------------
B1. TASKINPUT / TASKOUTPUT CONTRACTS [OBSERVED-INTERFACE] — Structured input (task+context+scope+dependencies) -> output (result+evidence+failure+retry). Direct extension of WorkerWorkProduct. Verdict: ADAPT (batch 1). Existing: ARCHITECTURE.md core flow; WorkerWorkProduct; IndependentValidation; ExecutionAuthorizationBoundary. Gap: No typed TaskInput/TaskOutput.
B2. TASKGRAPH / DAG [OBSERVED-INTERFACE] — Nodes + dependency edges; acyclic; failure propagates. Supports specialist roles. Verdict: ADAPT / DEFER. Existing: ARCHITECTURE.md Plan/Decomposition; role pools. Gap: No typed graph.
B3. DEPENDENCY / CONTEXT / FILE-SCOPE [OBSERVED-INTERFACE] — Explicit file-scope per node; bounded workspace access. Reinforces invariant 11. Verdict: ADOPT / PRESERVE. Existing: ARCHITECTURE.md workspace authority + mutation lock + exact targets. Gap: None (optional formalization).
B4. ARTIFACT CONTRACT [OBSERVED-INTERFACE] — Structured artifact (type, content, evidence refs, redaction status, provenance, mutation state). Direct model for batch 2. Verdict: ADAPT (extension). Existing: Evidence flow; mutation attestation; SecretRedactor; fingerprint/status. Gap: No typed artifact object; no provenance tracking.
B5. FAILURE CLASSIFICATION / REMEDIATION [OBSERVED-INTERFACE] — Types (validation/auth/execution/evidence) -> action (retry/rollback/repair/stop) -> policy. Verdict: ADAPT / DEFER. Existing: REPAIR/UNKNOWN/CONFLICT stops; rollback/verify; mutation failure preserves evidence. Gap: No typed classification; no retry-policy.
B6. REVIEWER / VALIDATION SEPARATION [OBSERVED-INTERFACE] — Author -> Independent validator -> Reviewer -> Execution authorization; roles separated; evidence produced at each stage. Verdict: ADOPT / PRESERVE. Existing: IndependentValidator; ExecutionAuthorizationBoundary; evidence takes precedence.
B7. RUNTIME TASK STATE / RECOVERY [OBSERVED-INTERFACE] — State tracked (pending/running/completed/failed/rolled back); recovery uses last valid state; restart avoids re-execution; evidence preserved. Verdict: ADAPT / DEFER. Existing: Checkpoint; rollback/verify; mutation attestation; independent validation. Gap: No explicit state contract.

C. CODDESS — EXTRACTED MECHANISMS
-----------------------------------
C1. PROVIDER GATEWAY / ABSTRACTION [VERIFIED — connection_manager / PROVIDER_PREFIXES / PROVIDER_FILES / resolve_secret_file / import_provider] — Gateway over existing connection_manager; adapter not replacement. Verdict: ADAPT (batch 2/3). Existing: connection_manager contracts; provider_transport _resolve_key. Gap: No unified gateway interface (selection/resolution distributed).
C2. PROVIDER NORMALIZATION [OBSERVED-INTERFACE] — Provider inputs/outputs/errors normalized; rules documented. Verdict: ADAPT / DEFER. Existing: PROVIDER_PREFIXES; fingerprint/status normalization.
C3. CONNECTION / ACCOUNT SELECTION [VERIFIED — f3e1423 / credential_pool_manager / connection_manager / provider_transport] — Pool selection + health (fingerprint/status only) + reload/rebind + rotation. All 7 tests PASS; real source integration; atomic swap; failure preservation; concurrent overload; stale-candidate guard verified. Verdict: ADOPT / PRESERVE. Existing: reload_credential_pool; get_active_pool; get_pool_health; resolve_secret_file; fingerprint.
C4. EVENT / RUNTIME NORMALIZATION [OBSERVED-INTERFACE] — Normalized event format; observation/monitoring only; no mutation authority. Verdict: ADAPT / DEFER. Existing: Evidence flow; fingerprint/status observation.
C5. WORKSPACE MODEL [VERIFIED — ARCHITECTURE.md workspace/tool/external authority + mutation control] — Bounded scope; workspace identity; declared mutation targets; mutation requires exact targets. Verdict: ADOPT / PRESERVE. Existing: Workspace authority; mutation lock; exact target verification; GitMutationExecutor.

D. CONTROL CENTER — EXTRACTED MECHANISMS
-----------------------------------------
D1. SERVER / CLIENT AUTHORITY SPLIT [VERIFIED — ARCHITECTURE.md invariant 24-26 / PRODUCT_UI_SPEC.md / DesktopAppService concept] — Server owns mutation/state; client submits intents; server validates/auth/executes; client receives observations. Verdict: ADOPT / PRESERVE. Gap: No adapter/service contract formalized (desktop UI deferred).
D2. AGENT / TASK LIFECYCLE [VERIFIED — ARCHITECTURE.md core flow / EXECUTION_GATE_PROCESS_BOUNDARY.md] — Discovery->Planning->Execution->Validation->Auth->Gate->Mutation->Verification->Approve/Rollback; evidence at each stage. Verdict: ADOPT / PRESERVE. Gap: No structured lifecycle observation contract for UI.
D3. WORKTREE ISOLATION [VERIFIED — f3e1423 concurrent reload + mutation control + clean index/HEAD verification] — Bounded workspace; exact targets; unrelated worktree/index rejected; rollback verifies clean state. Verdict: ADOPT / PRESERVE. Existing: GitMutationExecutor; mutation lock; rollback/verify; concurrent overload verified.
D4. EXECUTION LOCK / CLAIM MODEL [VERIFIED — f3e1423 _pool_lock + _swap_lock + _reload_sequence + _last_swapped_seq] — Lock during preflight/staging/verification/commit; sequence prevents stale replacement; failure preserves previous state. Verdict: ADOPT / PRESERVE (verified; claim-formalization deferred).
D5. CAPABILITY / PERMISSION MODEL [VERIFIED — ARCHITECTURE.md invariant 3 / 13 / resource authority] — Workspace/tool/external domains; authorization promotes validated tasks; pool configurable; identity IDs only; no fixed max. Verdict: ADOPT / PRESERVE (existing; capability object deferred).
D6. FLEET / RUNTIME STATE [OBSERVED-INTERFACE / verified via get_active_pool + get_pool_health] — Role/connection/health/workload observation; fingerprint/status only; deep-copy; projection redacted; read-only. Verdict: ADAPT / DEFER (structured projection deferred to batch 4). Existing: get_active_pool; get_pool_health; credential_pool_manager active pool.
D7. EVIDENCE / REVIEW FLOW [VERIFIED — ARCHITECTURE.md evidence flow / mutation attestation / rollback verify] — Evidence at each stage; review validates; authorization promotes evidence; rollback verifies; mutation verifies exact targets/content. Verdict: ADOPT / PRESERVE (structured artifact deferred).
D8. DESKTOP UI / CONTROL CENTER SCREEN COVERAGE [VERIFIED — PRODUCT_UI_SPEC.md / ARCHITECTURE.md invariant 26] — Professional Windows desktop (Dashboard/Chat/Projects/Connections/Run/Plan/Workers/Evidence/Git/Tests/Safety/Settings); adapter/service over core; typed contracts; redaction required; real desktop acceptance required (not mockup). Verdict: ADAPT / DEFER (post-Contract Consolidation; desktop UI is final consumer, not creator; Batch 4 not started).

WHAT WE SHOULD ACTUALLY BORROW — CROSS-PROJECT SYNTHESIS
------------------------------------------------------------
A. ALREADY HAVE (preserve; no change): Core authority separation; IndependentValidator; ExecutionAuthorizationBoundary; ExecutionGate; GitMutationExecutor; evidence flow; credential authority (f3e1423); redaction; WorkerWorkProduct; worktree isolation; capability design; execution locks/sequence guard.
B. ADAPT INTO EXISTING (recommended Contract Consolidation batch 1-2): Typed task contract (B1), structured artifacts (B4), provider/account abstraction (C3 — adapter over connection_manager), state projection (D6), event stream (B4/C4 — adapter), capability formalization (D5).
C. NEW CONTRACTS (deferred): Formal TaskGraph (B2 — optional), capability revocation (D5 — deferred), workspace projection interface (D6 — minimal adapter sufficient), full gateway formalization (C1 — adapter sufficient).
D. DEFER (post-Contract Consolidation; desktop UI after contracts stable): Desktop Control Center (D8 — adapter/service only after stable contracts + real desktop acceptance); full fleet projection (D6); runtime event formalization (C4/B4); structured recovery (B5 — existing sufficient).
E. REJECTED (would create second authority / replace existing): Replacing WorkerWorkProduct with Hivemind artifacts; second routing/registry; second policy; second mutation authority; second execution authority; replacing IndependentValidator; replacing credential authority (connection_manager/pool); replacing SecretRedactor.

AUTHORITY / SECURITY NOTES
--------------------------
- No mechanism replaces WorkerWorkProduct, IndependentValidator, ExecutionAuthorizationBoundary, ExecutionGate, GitMutationExecutor, credential authority, or SecretRedactor.
- All adapter mechanisms (UI, gateway, projection, event) are read/submit only; mutation requires authorization + gate + exact targets + mutation lock + verified HEAD.
- All observation uses fingerprint/status only; redaction required before observable.
- All new contracts extend rather than replace; no architecture rewrite; no duplication of core authority.
- Desktop Control Center deferred until Contract Consolidation completes; desktop UI is consumer, never creator, of contracts.
- f3e1423 verified all credential behaviors (real source reload, atomic swap, deep-copy, fingerprint-only, failure preservation, concurrent overload, stale-candidate guard). No additional implementation required for harvest.

VERIFICATION STATUS
-------------------
- Credential milestone: f3e1423 (all 7 tests PASS; compile PASS; no unrelated file changes).
- Benchmark matrix: 7ff60db (ARCHITECTURE_BENCHMARK_MATRIX.md; clean working tree; remote matches).
- Harvest: ARCHITECTURE_HARVEST.md (research only; no implementation; no modifications to existing files; no Contract Consolidation started; no Batch 4; no desktop UI; no new dependencies; no external code imported).
