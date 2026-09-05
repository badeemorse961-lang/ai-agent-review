from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REGISTRY_FILE = BASE_DIR / "connections.json"
ROLES_FILE = BASE_DIR / "roles.json"

ROLES = {
    "central_leader": {
        "type": "leader",
        "connections": [],
        "active_connection": None,
    },
    "architect": {
        "type": "worker",
        "connections": [],
    },
    "coder": {
        "type": "worker",
        "connections": [],
    },
    "debugger": {
        "type": "worker",
        "connections": [],
    },
    "tester": {
        "type": "worker",
        "connections": [],
    },
    "reviewer": {
        "type": "worker",
        "connections": [],
    },
}


def load_registry() -> dict:
    if not REGISTRY_FILE.exists():
        raise FileNotFoundError(
            f"Missing connection registry: {REGISTRY_FILE}"
        )

    return json.loads(
        REGISTRY_FILE.read_text(encoding="utf-8")
    )


def save_roles(data: dict) -> None:
    ROLES_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    registry = load_registry()

    connection_ids = list(
        registry.get("connections", {}).keys()
    )

    roles = json.loads(
        json.dumps(ROLES)
    )

    # No role is assigned yet.
    # All 26 connections remain unassigned until we
    # complete capability/leader evaluation.

    data = {
        "version": 1,
        "roles": roles,
        "unassigned_connections": connection_ids,
    }

    save_roles(data)

    print("Role manager initialized.")
    print(f"Connections available: {len(connection_ids)}")
    print("Assigned to roles    : 0")
    print(f"Unassigned            : {len(connection_ids)}")
    print(f"Roles file            : {ROLES_FILE.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())