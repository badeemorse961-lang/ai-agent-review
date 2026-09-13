import sys
from pathlib import Path
sys.path.insert(0,"/projects")
from project_scanner import ProjectScanner
from project_state_classifier import ProjectStateClassifier
from secret_redaction import SecretRedactor
from ui.read_models.desktop_projection import DesktopProjection

class DesktopAppService:
    def get_projection(self, workspace_root: str) -> DesktopProjection:
        workspace_exists = Path(workspace_root).exists()
        scanner = ProjectScanner(Path(workspace_root)) if workspace_exists else None
        manifest = scanner.scan() if scanner else {}
        classifier = ProjectStateClassifier()
        try:
            classification = classifier.classify(manifest)
            project_state = str(classification.result.state)
        except Exception:
            project_state = "MISSING READ CONTRACT"
        git_info = manifest.get("git") if isinstance(manifest, dict) else {}
        return DesktopProjection(
            workspace_path=workspace_root if workspace_exists else None,
            project_state=project_state,
            run_phase="MISSING READ CONTRACT",
            leader_connection_id="MISSING READ CONTRACT",
            failover_status="MISSING READ CONTRACT",
            worker_pool_summary="MISSING READ CONTRACT",
            current_task="MISSING READ CONTRACT",
            validation_verdict=None,
            latest_test_result="MISSING READ CONTRACT",
            git_branch=git_info.get("branch") if isinstance(git_info, dict) else None,
            git_head_sha=git_info.get("head_sha") if isinstance(git_info, dict) else None,
            git_dirty_state=git_info.get("dirty_state") if isinstance(git_info, dict) else None,
            mutation_lock_state="MISSING READ CONTRACT",
            safety_stop_reason="MISSING READ CONTRACT",
            last_run_timestamp="MISSING READ CONTRACT",
        )
