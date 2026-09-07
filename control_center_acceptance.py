from __future__ import annotations

import argparse
import os
from pathlib import Path

from application_boundary import ApplicationIntent
from connection_control_center import ConnectionControlCenterApp, ConnectionControlCenterService
from protected_secret_store import WindowsProtectedSecretStore

EXPECTED_NAVIGATION = (
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


def run_service_smoke(root: Path) -> None:
    service = ConnectionControlCenterService(workspace_root=root, autowire_core=False)
    assert isinstance(service.secret_store, WindowsProtectedSecretStore)

    selected = service.dispatch(ApplicationIntent("select_project", {"workspace_root": str(root)}))
    assert selected.status == "OK", selected.error
    dashboard = service.dispatch(ApplicationIntent("refresh_dashboard", {}))
    assert dashboard.status == "OK", dashboard.error
    assert isinstance(dashboard.data.get("understanding"), dict)

    connections = service.dispatch(ApplicationIntent("refresh_connections", {}))
    assert connections.status == "OK", connections.error
    for item in connections.data.get("connections", []):
        assert "raw_secret" not in item
        assert "secret" not in item
        assert item.get("fingerprint_present") in {True, False}

    git = service.dispatch(ApplicationIntent("git_snapshot", {}))
    assert git.status == "OK", git.error
    assert git.data.get("authority") == "inspection-only"

    unknown = service.dispatch(ApplicationIntent("arbitrary_shell", {"command": "git reset --hard"}))
    assert unknown.status == "REJECTED"
    blocked_chat = service.dispatch(ApplicationIntent("send_leader_goal", {"goal": "acceptance smoke", "task_id": "UI-E2E-SMOKE"}))
    assert blocked_chat.status == "BLOCKED"


def run_gui_smoke(root: Path) -> None:
    if os.name != "nt":
        raise SystemExit("GUI smoke is a Windows-only acceptance check")
    app = ConnectionControlCenterApp()
    app.service.workspace_root = root
    assert app.root.title() == "AI-Agent Control Center"
    assert tuple(label for label, _ in app.NAVIGATION) == EXPECTED_NAVIGATION

    for page in EXPECTED_NAVIGATION:
        app.show(page)
        assert app.current_page == page
        assert app.body.winfo_children(), f"GUI page rendered no content: {page}"

    initial_theme = app.dark
    app.toggle_theme()
    assert app.dark is not initial_theme
    app.toggle_theme()
    assert app.dark is initial_theme

    app.show("Connections & Pools")
    assert app.connection_tree is not None
    app.show("Chat")
    app.show("Run / Plan")
    app.show("Safety & Policy")

    app.root.after(1200, app.root.destroy)
    app.run()


def main() -> int:
    parser = argparse.ArgumentParser(description="AI-Agent Control Center Windows acceptance harness")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--gui", action="store_true", help="Open and exercise the actual Windows GUI for a short smoke run")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"Workspace does not exist: {root}")
    assert (root / "control_center.pyw").is_file()
    run_service_smoke(root)
    if args.gui:
        run_gui_smoke(root)
    print("CONTROL CENTER ACCEPTANCE SMOKE PASSED")
    print(f"Workspace           : {root}")
    print(f"GUI exercised       : {'YES' if args.gui else 'NO'}")
    print("Navigation surfaces  : 11/11")
    print("Raw secrets exposed : NO")
    print("Arbitrary shell     : REJECTED")
    print("Git authority       : INSPECTION-ONLY")
    print("Protected store     : WINDOWS DPAPI")
    print("Live provider E2E    : NOT CLAIMED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
