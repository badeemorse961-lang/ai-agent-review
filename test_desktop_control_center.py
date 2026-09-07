from __future__ import annotations

import importlib


def test_desktop_control_center_module_imports_without_starting_ui() -> None:
    module = importlib.import_module("desktop_control_center")
    assert hasattr(module, "ControlCenterApp")
    assert callable(module.main)


def test_user_facing_windows_entry_point_exists() -> None:
    from pathlib import Path
    assert Path("control_center.pyw").is_file()
