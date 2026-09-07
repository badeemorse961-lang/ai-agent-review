from __future__ import annotations

from pathlib import Path

from application_boundary import ApplicationIntent, ControlCenterService
from control_center_i18n import _TRANSLATIONS, _translate
from control_center_language_runtime import TRANSLATIONS as RUNTIME_TRANSLATIONS
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
    assert "ConnectionControlCenterApp" in entry_point
    assert "from control_center_safety_view import install_real_safety_view" in entry_point
    assert "from control_center_language_runtime_v2 import install_bilingual_support" in entry_point
    assert "from control_center_window_runtime import install_responsive_window" in entry_point
    assert "from control_center_sidebar_runtime import install_scrollable_sidebar" in entry_point
    assert "from control_center_visual_runtime import install_visual_runtime" in entry_point
    assert "install_bilingual_support(ConnectionControlCenterApp)" in entry_point
    assert "install_responsive_window(ConnectionControlCenterApp)" in entry_point
    assert "install_scrollable_sidebar(ConnectionControlCenterApp)" in entry_point
    assert "install_visual_runtime(ConnectionControlCenterApp)" in entry_point
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


def test_bilingual_support_has_real_arabic_translations_for_product_surface() -> None:
    required = {
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
        "Toggle theme",
        "Exit",
    }
    assert required.issubset(_TRANSLATIONS)
    assert required.issubset(RUNTIME_TRANSLATIONS)
    for text in required:
        translated = _translate(text, "ar")
        assert translated != text
        assert translated.strip()


def test_bilingual_runtime_is_reversible_visible_and_rtl_aware() -> None:
    source = Path("control_center_language_runtime.py").read_text(encoding="utf-8")
    runtime = Path("control_center_language_runtime_v2.py").read_text(encoding="utf-8")
    assert 'self.language = "ar" if getattr(self, "language", "en") == "en" else "en"' in source
    assert 'before=self.theme_button' in source
    assert 'anchor="e", justify="right"' in source
    assert 'anchor="w", justify="left"' in source
    assert 'text="العربية"' in source
    assert 'text="English"' in source
    assert '_install_base(app_class)' in runtime
    assert 'button.configure(text=_button_text(getattr(self, "language", "en")))' in runtime


def test_safety_evidence_binds_affected_task_from_application_intent() -> None:
    source = Path("application_boundary.py").read_text(encoding="utf-8")
    safety_view = Path("control_center_safety_view.py").read_text(encoding="utf-8")
    assert 'task_id = intent.payload.get("task_id")' in source
    assert 'if isinstance(task_id, str) and task_id.strip()' in source
    assert 'event["task_id"] = task_id.strip()' in source
    assert 'event.get("task_id")' in safety_view


def test_responsive_window_runtime_is_integrated() -> None:
    source = Path("control_center_window_runtime.py").read_text(encoding="utf-8")
    assert "winfo_screenwidth" in source
    assert "winfo_screenheight" in source
    assert "root.resizable(True, True)" in source
    assert "_install_scrollable_body" in source
    assert "Scrollbar" in source


def test_sidebar_runtime_is_integrated_and_keeps_navigation_accessible() -> None:
    entry_point = Path("control_center.pyw").read_text(encoding="utf-8")
    source = Path("control_center_sidebar_runtime.py").read_text(encoding="utf-8")
    assert "install_scrollable_sidebar(ConnectionControlCenterApp)" in entry_point
    assert "_cc_sidebar_scrollbar" in source
    assert "<MouseWheel>" in source
    assert "place(" in source
    assert "self._cc_sidebar_nav" in source


def test_visual_runtime_preserves_sidebar_readability_on_small_windows() -> None:
    source = Path("control_center_visual_runtime.py").read_text(encoding="utf-8")
    assert 'font=("Segoe UI", 10, "bold")' in source
    assert 'self.root.grid_columnconfigure(0, minsize=224)' in source
    assert 'wraplength=198' in source
    assert 'sidebar.configure(width=224)' in source
    assert 'height=42' in source
