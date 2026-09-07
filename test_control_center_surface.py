from __future__ import annotations

from pathlib import Path

from application_boundary import ApplicationIntent, ControlCenterService
from desktop_control_center import ControlCenterApp


def test_control_center_exposes_required_navigation_surface() -> None:
    labels = tuple(label for label, _ in ControlCenterApp.NAVIGATION)
    assert labels == (
        "Dashboard",
        "Chat",
        "Projects",
        "Connections & Pools",
        "Workers",
        "Run / Plan",
        "Evidence & Activity",
        "Git & Changes",
        "Tests & Verification",
        "Safety & Policy",
        "Settings / Diagnostics",
    )


def test_application_boundary_rejects_shell_and_unknown_intents() -> None:
    service = ControlCenterService(autowire_core=False)
    arbitrary_shell = service.dispatch(
        ApplicationIntent("arbitrary_shell", {"command": "git reset --hard"})
    )
    assert arbitrary_shell.status == "REJECTED"


def test_windows_entry_point_is_non_console_launcher() -> None:
    entry_point = Path("control_center.pyw").read_text(encoding="utf-8")
    assert "from desktop_control_center import main" in entry_point
    assert "subprocess" not in entry_point
    assert "powershell" not in entry_point.lower()


def test_control_center_service_exposes_only_structured_ui_actions() -> None:
    service = ControlCenterService(autowire_core=False)
    handlers = {
        "select_project",
        "refresh_dashboard",
        "send_leader_goal",
        "run_task",
        "refresh_connections",
        "import_provider_connections",
        "git_snapshot",
        "session_evidence",
    }
    for kind in handlers:
        result = service.dispatch(ApplicationIntent(kind, {}))
        assert result.status in {"OK", "REJECTED", "BLOCKED", "NOT_CONFIGURED", "ERROR"}


def test_dashboard_binds_project_card_to_core_understanding_state() -> None:
    source = Path("desktop_control_center.py").read_text(encoding="utf-8")
    assert 'understanding = self._mapping(data.get("understanding"))' in source
    assert 'classification = self._mapping(understanding.get("classification"))' in source
    assert '"state": classification.get("state", "UNKNOWN")' in source
    assert '"workspace": understanding.get("workspace"' in source
