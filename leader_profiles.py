from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config_registry import (
    get_leader_pool,
    load_registry,
    validate_registry,
)


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = BASE_DIR / "leader_profiles.json"


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    registry = validate_registry()
    leader = load_registry()["architecture"]["leader"]

    primary_pool = get_leader_pool("primary")
    failover_pool = get_leader_pool("failover")

    profiles = {
        "version": 3,
        "source": "config/registry.json",
        "architecture": {
            "provider": leader["provider"],
            "strategy": "model-aware-primary-failover",
            "primary_model": leader["primary_model"],
            "failover_model": leader["failover_model"],
            "safe_stop_on_exhaustion": bool(
                leader.get("safe_stop_on_exhaustion", True)
            ),
        },
        "pools": {
            "primary": {
                "provider": leader["provider"],
                "model": leader["primary_model"],
                "connections": primary_pool,
            },
            "failover": {
                "provider": leader["provider"],
                "model": leader["failover_model"],
                "connections": failover_pool,
            },
        },
        "runtime": {
            "active_tier": "primary",
            "active_connection": primary_pool[0],
            "active_model": leader["primary_model"],
            "primary_index": 0,
            "failover_index": 0,
            "state": "READY",
            "failure_history": [],
        },
    }

    save_json(OUTPUT_FILE, profiles)

    print("=" * 70)
    print("LEADER PROFILES DERIVED FROM REGISTRY")
    print("=" * 70)
    print(f"Primary model : {leader['primary_model']}")
    print(f"Primary count : {len(primary_pool)}")
    print(f"Failover model: {leader['failover_model']}")
    print(f"Failover count: {len(failover_pool)}")
    print(f"Saved         : {OUTPUT_FILE.name}")
    print("Result        : VALID ✅")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
