# Batch 3 — thin projection-view boundary. No framework dependency.
import sys
sys.path.insert(0,"/projects")
from ui.read_models.desktop_projection import DesktopProjection

class DashboardView:
    """Renders DesktopProjection; never accesses Core directly."""
    def __init__(self):
        self.projection = None
    def render(self, proj: DesktopProjection) -> str:
        self.projection = proj  # projection reference only; frozen/immutable
        lines = [
            "=== DESKTOP CONTROL CENTER ===",
            f"Workspace: {proj.workspace_path or 'None'}",
            f"Project State: {proj.project_state or 'None'}",
            f"Git Branch: {proj.git_branch or 'None'}",
            f"Git Head: {proj.git_head_sha or 'None'}",
            f"Git Dirty: {proj.git_dirty_state or 'None'}",
            "--- Read Contract Status ---",
            f"Run Phase: {proj.run_phase}",
            f"Leader Connection: {proj.leader_connection_id}",
            f"Failover: {proj.failover_status}",
            f"Worker Pool: {proj.worker_pool_summary}",
            f"Task: {proj.current_task}",
            f"Validation: {proj.validation_verdict}",
            f"Test: {proj.latest_test_result}",
            f"Mutation Lock: {proj.mutation_lock_state}",
            f"Safety: {proj.safety_stop_reason}",
            f"Timestamp: {proj.last_run_timestamp}",
        ]
        return "\n".join(lines)
    def refresh(self, projection: DesktopProjection) -> str:
        # Manual refresh: new projection replaces old; no orchestration
        return self.render(projection)
