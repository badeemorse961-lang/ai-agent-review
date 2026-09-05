from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent

ROLES_FILE = BASE_DIR / "roles.json"
HEALTH_FILE = BASE_DIR / "groq_worker_health.json"
OUTPUT_FILE = BASE_DIR / "worker_profiles.json"

WORKER_MODEL = "openai/gpt-oss-120b"

WORKER_ROLES = [
    "coder",
    "debugger",
    "tester",
    "architect",
    "reviewer",
    "standby",
]


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing file: {path.name}"
        )

    with path.open(
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def save_json(
    path: Path,
    data: dict[str, Any],
) -> None:
    with path.open(
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )


def unique(items: list[str]) -> list[str]:
    seen = set()
    result = []

    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return result


def main() -> int:
    roles = load_json(
        ROLES_FILE
    )

    health = load_json(
        HEALTH_FILE
    )

    healthy_connections = set(
        health.get(
            "healthy_connections",
            [],
        )
    )

    if not healthy_connections:
        raise RuntimeError(
            "No healthy Groq worker connections available."
        )

    role_data = roles.get(
        "roles",
        {},
    )

    workers: dict[str, Any] = {}

    all_assigned = []

    for role_name in WORKER_ROLES:
        role = role_data.get(
            role_name
        )

        if not role:
            raise RuntimeError(
                f"Missing worker role: {role_name}"
            )

        configured_connections = unique(
            role.get(
                "connections",
                [],
            )
        )

        if not configured_connections:
            raise RuntimeError(
                f"Worker role has no connections: "
                f"{role_name}"
            )

        healthy_role_connections = [
            connection
            for connection in configured_connections
            if connection in healthy_connections
        ]

        if role_name != "standby" and not healthy_role_connections:
            raise RuntimeError(
                f"No healthy connections remain "
                f"for required worker role: "
                f"{role_name}"
            )

        workers[role_name] = {
            "type": "worker",
            "provider": "groq",
            "model": WORKER_MODEL,

            "configured_connections":
                configured_connections,

            "healthy_connections":
                healthy_role_connections,

            "active_connection":
                (
                    healthy_role_connections[0]
                    if healthy_role_connections
                    else None
                ),

            "state": (
                "READY"
                if healthy_role_connections
                else "STANDBY_ONLY"
            ),
        }

        all_assigned.extend(
            configured_connections
        )

    # ---------------------------------------------------------
    # Validate connection ownership
    # ---------------------------------------------------------

    if len(
        all_assigned
    ) != 15:
        raise RuntimeError(
            "Expected exactly 15 Groq worker assignments."
        )

    if len(
        set(all_assigned)
    ) != 15:
        raise RuntimeError(
            "Duplicate Groq worker assignment detected."
        )

    expected_connections = {
        f"GROQ-{index:02d}"
        for index in range(1, 16)
    }

    if set(all_assigned) != expected_connections:
        missing = sorted(
            expected_connections
            - set(all_assigned)
        )

        extra = sorted(
            set(all_assigned)
            - expected_connections
        )

        raise RuntimeError(
            "Groq worker assignment mismatch. "
            f"Missing={missing}, "
            f"Extra={extra}"
        )

    # ---------------------------------------------------------
    # Runtime state
    # ---------------------------------------------------------

    output = {
        "version": 1,

        "architecture": {
            "provider": "groq",
            "model": WORKER_MODEL,

            "roles": [
                "coder",
                "debugger",
                "tester",
                "architect",
                "reviewer",
            ],

            "standby_role": "standby",

            "safe_stop_on_required_role_exhaustion": True,
        },

        "health_source": HEALTH_FILE.name,

        "healthy_worker_count": len(
            healthy_connections
        ),

        "workers": workers,

        "runtime": {
            "state": "READY",
            "active_role": None,
            "active_connection": None,
            "active_model": None,
        },
    }

    save_json(
        OUTPUT_FILE,
        output,
    )

    # ---------------------------------------------------------
    # Output
    # ---------------------------------------------------------

    print("=" * 70)
    print("GROQ WORKER PROFILES INITIALIZED")
    print("=" * 70)

    print()
    print(
        f"Worker model : {WORKER_MODEL}"
    )

    print(
        f"Healthy Groq : "
        f"{len(healthy_connections)}/15"
    )

    print()

    for role_name in WORKER_ROLES:
        worker = workers[role_name]

        healthy = worker[
            "healthy_connections"
        ]

        print(
            f"{role_name:<10}: "
            f"{', '.join(worker['configured_connections'])}"
        )

        print(
            f"{'':10}  Healthy -> "
            f"{', '.join(healthy) if healthy else 'NONE'}"
        )

        print(
            f"{'':10}  Active  -> "
            f"{worker['active_connection']}"
        )

    print()
    print(
        "Required worker roles:"
    )

    required_ready = all(
        workers[role]["healthy_connections"]
        for role in [
            "coder",
            "debugger",
            "tester",
            "architect",
            "reviewer",
        ]
    )

    print(
        f"  {'READY ✅' if required_ready else 'NOT READY ❌'}"
    )

    print()
    print(
        "Standby:"
    )

    print(
        f"  {workers['standby']['active_connection']}"
    )

    print()
    print(
        f"Saved: {OUTPUT_FILE.name}"
    )

    print("=" * 70)

    if not required_ready:
        print(
            "RESULT: REQUIRED WORKER ROLE "
            "UNAVAILABLE ❌"
        )
        return 1

    print(
        "RESULT: ALL WORKER ROLES READY ✅"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())