# AppService — thin read-only adapter over existing Core contracts.
# No orchestration, no planning, no mutation, no authorization, no execution.
import sys
from pathlib import Path
sys.path.insert(0, "/projects")
from project_scanner import ProjectScanner
from project_state_classifier import ProjectStateClassifier
from secret_redaction import SecretRedactor
from ui.read_models.dashboard_read import DashboardSnapshot

class DashboardAppService:
    def get_snapshot(self, workspace_root: str) -> DashboardSnapshot:
        scanner = ProjectScanner(Path(workspace_root)) if Path(workspace_root).exists() else None
        try:
            scan_result = scanner.scan() if scanner else None
        except Exception:
            scan_result = None
        classifier = ProjectStateClassifier()
        try:
            classification = classifier.classify({})
            project_state = str(classification)
        except Exception:
            project_state = "MISSING READ CONTRACT"
        redactor = SecretRedactor.from_secrets([])
        return DashboardSnapshot(
            workspace_path=workspace_root if Path(workspace_root).exists() else None,
            project_state=project_state,
            run_phase="MISSING READ CONTRACT",
            leader_connection_id="MISSING READ CONTRACT",
            failover_status="MISSING READ CONTRACT",
            worker_pool_summary={},
            current_task=None,
            validation_verdict=None,
            latest_test_result="NOT RUN",
            git_branch="MISSING READ CONTRACT",
            git_head_sha="MISSING READ CONTRACT",
            git_dirty_state=None,
            mutation_lock_state="MISSING READ CONTRACT",
            safety_stop_reason="MISSING READ CONTRACT",
            last_run_timestamp=None,
        )
