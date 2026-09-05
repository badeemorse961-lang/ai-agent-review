from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config_registry import load_registry, validate_registry


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = BASE_DIR / "worker_profiles.json"


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    registry = validate_registry()
    workers_cfg = load_registry()["architecture"]["workers"]

    provider = workers_cfg["provider"]
    model = workers_cfg["model"]
    roles = workers_cfg["roles"]

    workers: dict[str, Any] = {}
    all_assigned: list[str] = []

    for role_name, configured_connections in roles.items():
        if not isinstance(configured_connections, list):
            raise RuntimeError(
                f"Invalid worker pool for role: {role_name}"
            )

        workers[role_name] = {
            "type": "worker",
            "provider": provider,
            "model": model,
            "configured_connections": list(configured_connections),
            "healthy_connections": list(configured_connections),
            "active_connection": (
                configured_connections[0]
                if configured_connections
                else None
            ),
            "state": (
                "READY"
                if configured_connections
                else "STANDBY_ONLY"
            ),
        }
        all_assigned.extend(configured_connections)

    if len(all_assigned) != len(set(all_assigned)):
        raise RuntimeError("Duplicate worker connection assignment detected")

    output = {
        "version": 2,
        "source": "config/registry.json",
        "architecture": {
            "provider": provider,
            "model": model,
            "roles": [
                role
                for role in roles
                if role != "standby"
            ],
            "standby_role": "standby",
            "safe_stop_on_required_role_exhaustion": bool(
                workers_cfg.get(
                    "safe_stop_on_required_role_exhaustion",
                    True,
                )
            ),
        },
        "workers": workers,
        "runtime": {
            "state": "READY",
            "active_role": None,
            "active_connection": None,
            "active_model": None,
        },
    }

    save_json(OUTPUT_FILE, output)

    print("=" * 70)
    print("WORKER PROFILES DERIVED FROM REGISTRY")
    print("=" * 70)
    print(f"Provider       : {provider}")
    print(f"Model          : {model}")
    print(f"Worker roles   : {len(roles)}")
    print(f"Worker accounts: {len(all_assigned)}")
    print(f"Saved          : {OUTPUT_FILE.name}")
    print("Result         : VALID ✅")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
