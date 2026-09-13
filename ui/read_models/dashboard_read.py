# DashboardSnapshot — read-only projection contract
# No secrets; no raw provider credentials; no raw prompts.
# Unavailable authoritative source = MISSING READ CONTRACT or explicit NOT RUN.

from dataclasses import dataclass
from typing import Optional, List

@dataclass(frozen=True)
class DashboardSnapshot:
    workspace_path: Optional[str]  # MISSING READ CONTRACT if not provided
    project_state: Optional[str]  # MISSING READ CONTRACT if unclassified
    run_phase: Optional[str]  # MISSING READ CONTRACT if no gate state; NOT fabricated
    leader_connection_id: Optional[str]  # MISSING READ CONTRACT if router unavailable
    failover_status: Optional[str]
    worker_pool_summary: Optional[dict]
    current_task: Optional[str]  # None = no active task
    validation_verdict: Optional[bool]
    latest_test_result: Optional[str]  # NOT RUN if never executed
    git_branch: Optional[str]
    git_head_sha: Optional[str]
    git_dirty_state: Optional[List[str]]
    mutation_lock_state: Optional[str]
    safety_stop_reason: Optional[str]
    last_run_timestamp: Optional[str]
