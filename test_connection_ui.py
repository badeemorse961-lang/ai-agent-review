from __future__ import annotations

from pathlib import Path


def test_connection_ui_uses_file_picker_and_lifecycle_actions() -> None:
    source = Path("connection_control_center.py").read_text(encoding="utf-8")
    assert "filedialog.askopenfilename" in source
    assert "import_provider_connections" in source
    assert "disable_connection" in source
    assert "enable_connection" in source
    assert "remove_connection" in source
    assert "confirmed" in source
    assert "imported_count" in source
    assert "already_present_count" in source
    assert "rejected_count" in source
    assert "NO_CHANGES" in source
    assert "Protected credential is unavailable" in source
    assert "setup_required" in source
    assert "✓ READY" in source
    assert "Automatic Use" in source
    assert "raw secret" not in source.lower()


def test_connection_ui_does_not_offer_assignment_authority() -> None:
    source = Path("connection_control_center.py").read_text(encoding="utf-8")
    assert "auto-assign" not in source.lower()
    assert "assign_connection" not in source
    assert "config/registry.json" in source


def test_user_entry_point_uses_connection_aware_app() -> None:
    entry = Path("control_center.pyw").read_text(encoding="utf-8")
    assert "ConnectionControlCenterApp" in entry
    assert "from desktop_control_center import ControlCenterApp, main" not in entry
    assert "subprocess" not in entry
    assert "powershell" not in entry.lower()
