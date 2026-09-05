from __future__ import annotations

import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ROLES_FILE = BASE_DIR / "roles.json"
CAPABILITIES_FILE = BASE_DIR / "leader_capabilities.json"


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path.name}")

    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    roles = load_json(ROLES_FILE)
    capabilities = load_json(CAPABILITIES_FILE)

    ultra_pool = capabilities.get("ultra_pool", [])
    super_pool = capabilities.get("super_pool", [])

    if not ultra_pool:
        raise RuntimeError("No Nemotron Ultra leader connections found.")

    if not super_pool:
        raise RuntimeError("No Nemotron Super failover connections found.")

    # All OpenRouter connections become leadership connections.
    leader_connections = sorted(
        set(ultra_pool) | set(super_pool)
    )

    if len(leader_connections) != 11:
        raise RuntimeError(
            f"Expected 11 OpenRouter leadership connections, "
            f"found {len(leader_connections)}."
        )

    # All 15 Groq connections become worker infrastructure.
    groq_connections = [
        f"GROQ-{i:02d}"
        for i in range(1, 16)
    ]

    worker_assignment = {
        "coder": groq_connections[0:4],
        "debugger": groq_connections[4:7],
        "tester": groq_connections[7:9],
        "architect": groq_connections[9:11],
        "reviewer": groq_connections[11:14],
        "standby": groq_connections[14:15],
    }

    new_roles = {
        "version": 2,
        "architecture": {
            "leadership_provider": "openrouter",
            "worker_provider": "groq",
            "primary_leader_model":
                "nvidia/nemotron-3-ultra-550b-a55b:free",
            "failover_leader_model":
                "nvidia/nemotron-3-super-120b-a12b:free",
        },
        "roles": {
            "central_leader": {
                "type": "leader",
                "provider": "openrouter",
                "connections": leader_connections,
                "active_connection": leader_connections[0],
                "model_strategy": {
                    "primary": {
                        "model":
                            "nvidia/nemotron-3-ultra-550b-a55b:free",
                        "pool": ultra_pool,
                    },
                    "failover": {
                        "model":
                            "nvidia/nemotron-3-super-120b-a12b:free",
                        "pool": super_pool,
                    },
                },
            },

            "coder": {
                "type": "worker",
                "provider": "groq",
                "connections": worker_assignment["coder"],
                "active_connection": None,
            },

            "debugger": {
                "type": "worker",
                "provider": "groq",
                "connections": worker_assignment["debugger"],
                "active_connection": None,
            },

            "tester": {
                "type": "worker",
                "provider": "groq",
                "connections": worker_assignment["tester"],
                "active_connection": None,
            },

            "architect": {
                "type": "worker",
                "provider": "groq",
                "connections": worker_assignment["architect"],
                "active_connection": None,
            },

            "reviewer": {
                "type": "worker",
                "provider": "groq",
                "connections": worker_assignment["reviewer"],
                "active_connection": None,
            },

            "standby": {
                "type": "standby",
                "provider": "groq",
                "connections": worker_assignment["standby"],
                "active_connection": None,
            },
        },

        "unassigned_connections": [],
    }

    # Validate that every known connection appears exactly once.
    assigned = []

    for role in new_roles["roles"].values():
        assigned.extend(role.get("connections", []))

    if len(assigned) != 26:
        raise RuntimeError(
            f"Expected 26 assigned connections, found {len(assigned)}."
        )

    if len(set(assigned)) != 26:
        raise RuntimeError("Duplicate connection assignment detected.")

    expected = set(
        leader_connections + groq_connections
    )

    if set(assigned) != expected:
        missing = sorted(expected - set(assigned))
        extra = sorted(set(assigned) - expected)

        raise RuntimeError(
            f"Connection assignment mismatch. "
            f"Missing={missing}, Extra={extra}"
        )

    save_json(ROLES_FILE, new_roles)

    print("=" * 70)
    print("FINAL ROLE ARCHITECTURE")
    print("=" * 70)

    print()
    print("LEADERSHIP")
    print(
        "  PRIMARY : Nemotron Ultra :free"
    )
    print(
        f"  POOL    : {', '.join(ultra_pool)}"
    )

    print(
        "  FAILOVER: Nemotron Super :free"
    )
    print(
        f"  POOL    : {', '.join(super_pool)}"
    )

    print()
    print("GROQ WORKERS")

    for role_name, connections in worker_assignment.items():
        print(
            f"  {role_name:<10}: "
            f"{', '.join(connections)}"
        )

    print()
    print("Total leadership connections :", len(leader_connections))
    print("Total Groq worker connections:", len(groq_connections))
    print("Total assigned               :", len(assigned))
    print()
    print(f"Updated: {ROLES_FILE.name}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())