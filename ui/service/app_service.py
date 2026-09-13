# AppService — thin read-only adapter over existing Core contracts.
# No orchestration, no planning, no mutation, no authorization, no execution.
# Dependency direction: this file -> existing Core only.

import sys
from pathlib import Path
sys.path.insert(0, "/projects")

from project_scanner import ProjectScanner
from project_state_classifier import ProjectStateClassifier
from secret_redaction import SecretRedactor
from ui.read_models.dashboard_read import DashboardSnapshot

class DashboardAppService:
    def get_snapshot(self, workspace_root: str) -> DashboardSnapshot:
        # Read-only projection; execution/mutation/auth paths not invoked
        scanner = ProjectScanner(Path(workspace_root))
        classifier = ProjectStateClassifier()
        redactor = SecretRedactor.from_secrets([])
        # Projection uses redactor; no secrets projected
        return DashboardSnapshot(
            workspace_path=workspace_root if Path(workspace_root).exists() else None,
            project_state="NOT CLASSIFIED",  # placeholder for contract demonstration only
            run_phase="NOT RUN",
            leader_connection_id=None,
            failover_status="MISSING READ CONTRACT",
            worker_pool_summary={},
            current_task=None,
            validation_verdict=None,
            latest_test_result="NOT RUN",
            git_branch=None,
            git_head_sha=None,
            git_dirty_state=[],
            mutation_lock_state="MISSING READ CONTRACT",
            safety_stop_reason=None,
            last_run_timestamp=None,
        )
