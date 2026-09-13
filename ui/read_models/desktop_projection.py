from dataclasses import dataclass
from typing import Optional, List

@dataclass(frozen=True)
class DesktopProjection:
    workspace_path: Optional[str]
    project_state: Optional[str]
    run_phase: Optional[str]
    leader_connection_id: Optional[str]
    failover_status: Optional[str]
    worker_pool_summary: Optional[str]
    current_task: Optional[str]
    validation_verdict: Optional[bool]
    latest_test_result: Optional[str]
    git_branch: Optional[str]
    git_head_sha: Optional[str]
    git_dirty_state: Optional[List[str]]
    mutation_lock_state: Optional[str]
    safety_stop_reason: Optional[str]
    last_run_timestamp: Optional[str]
