from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REGISTRY_FILE = BASE_DIR / "connections.json"
ROLES_FILE = BASE_DIR / "roles.json"


PLAN = {
    "central_leader": {
        "groq": 4,
        "openrouter": 2,
    },
    "coder": {
        "groq": 3,
        "openrouter": 1,
    },
    "debugger": {
        "groq": 2,
        "openrouter": 1,
    },
    "tester": {
        "groq": 1,
        "openrouter": 2,
    },
    "architect": {
        "groq": 1,
        "openrouter": 2,
    },
    "reviewer": {
        "groq": 1,
        "openrouter": 3,
    },
    "standby": {
        "groq": 3,
        "openrouter": 0,
    },
}


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(path)

    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    registry = load_json(REGISTRY_FILE)

    connections = registry.get("connections", {})
    if len(connections) != 26:
        raise RuntimeError(
            f"Expected 26 connections, found {len(connections)}"
        )

    by_provider = {
        "groq": [],
        "openrouter": [],
    }

    for connection_id, info in connections.items():
        provider = info.get("provider")
        if provider not in by_provider:
            raise RuntimeError(
                f"Unknown provider for {connection_id}: {provider}"
            )

        by_provider[provider].append(connection_id)

    by_provider["groq"].sort()
    by_provider["openrouter"].sort()

    used: set[str] = set()
    assigned: dict[str, list[str]] = {}

    for role, counts in PLAN.items():
        selected: list[str] = []

        for provider, count in counts.items():
            available = [
                cid
                for cid in by_provider[provider]
                if cid not in used
            ]

            if len(available) < count:
                raise RuntimeError(
                    f"Not enough {provider} connections "
                    f"for role {role}: need {count}, "
                    f"have {len(available)}"
                )

            chosen = available[:count]
            selected.extend(chosen)
            used.update(chosen)

        assigned[role] = selected

    if len(used) != 26:
        raise RuntimeError(
            f"Assignment error: only {len(used)}/26 assigned"
        )

    roles = {
        "version": 1,
        "roles": {},
        "unassigned_connections": [],
    }

    for role, connection_ids in assigned.items():
        role_type = "leader" if role == "central_leader" else "worker"

        roles["roles"][role] = {
            "type": role_type,
            "connections": connection_ids,
            "active_connection": (
                connection_ids[0]
                if role == "central_leader" and connection_ids
                else None
            ),
        }

    roles["roles"]["standby"]["type"] = "standby"

    # Write role information back into the connection registry.
    for connection_id, info in connections.items():
        info["role"] = None

    for role, connection_ids in assigned.items():
        for connection_id in connection_ids:
            connections[connection_id]["role"] = role

    save_json(REGISTRY_FILE, registry)
    save_json(ROLES_FILE, roles)

    print("=" * 60)
    print("ROLE ASSIGNMENT COMPLETE")
    print("=" * 60)

    for role, connection_ids in assigned.items():
        print(
            f"{role:<18}: "
            f"{len(connection_ids)} -> "
            f"{', '.join(connection_ids)}"
        )

    print("=" * 60)
    print(f"Total assigned: {len(used)}/26")
    print("Unassigned    : 0")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())