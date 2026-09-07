from __future__ import annotations

import argparse
import os
from pathlib import Path

from application_boundary import ApplicationIntent, ControlCenterService


def run_service_smoke(root: Path) -> None:
    service = ControlCenterService(workspace_root=root)

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

    git = service.dispatch(ApplicationIntent("git_snapshot", {}))
    assert git.status == "OK", git.error
    assert git.data.get("authority") == "inspection-only"

    unknown = service.dispatch(ApplicationIntent("arbitrary_shell", {"command": "git reset --hard"}))
    assert unknown.status == "REJECTED"

    blocked_chat = service.dispatch(
        ApplicationIntent("send_leader_goal", {"goal": "acceptance smoke", "task_id": "UI-E2E-SMOKE"})
    )
    assert blocked_chat.status == "BLOCKED"


def run_gui_smoke(root: Path) -> None:
    if os.name != "nt":
        raise SystemExit("GUI smoke is a Windows-only acceptance check")
    from desktop_control_center import ControlCenterApp

    service = ControlCenterService(workspace_root=root)
    app = ControlCenterApp(service)
    assert app.root.title() == "AI-Agent Control Center"
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
    print("Raw secrets exposed : NO")
    print("Arbitrary shell     : REJECTED")
    print("Git authority       : INSPECTION-ONLY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
