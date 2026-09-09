from __future__ import annotations

from pathlib import Path


def test_connection_ui_uses_file_picker_and_full_lifecycle_surface() -> None:
    source = Path("connection_control_center.py").read_text(encoding="utf-8")
    for token in (
        "filedialog.askopenfilename",
        "replace_connection_credential",
        "validate_connection",
        "disable_connection",
        "enable_connection",
        "remove_connection",
        "Refresh External Sources",
        "PENDING_ASSIGNMENT",
        "routable",
        "Fingerprint",
        "Credential",
        "Readiness",
    ):
        assert token in source
    for forbidden in ("read_secret_source", "import_provider(", "import_known_provider_credentials", "fingerprint(", "SecretStore", "WindowsProtectedSecretStore"):
        assert forbidden not in source


def test_connection_ui_does_not_offer_assignment_authority() -> None:
    source = Path("connection_control_center.py").read_text(encoding="utf-8")
    assert "auto-assign" not in source.lower()
    assert "assign_connection" not in source


def test_user_entry_point_uses_connection_aware_app() -> None:
    entry = Path("control_center.pyw").read_text(encoding="utf-8")
    assert "ConnectionControlCenterApp" in entry
    assert "subprocess" not in entry
    assert "powershell" not in entry.lower()
