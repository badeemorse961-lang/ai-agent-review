from __future__ import annotations

import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent

ROLES_FILE = BASE_DIR / "roles.json"
CAPABILITIES_FILE = BASE_DIR / "leader_capabilities.json"
OUTPUT_FILE = BASE_DIR / "leader_profiles.json"


PRIMARY_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
FAILOVER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path.name}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def unique(items: list[str]) -> list[str]:
    seen = set()
    result = []

    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return result


def main() -> int:
    roles = load_json(ROLES_FILE)
    capabilities = load_json(CAPABILITIES_FILE)

    leader_role = roles["roles"]["central_leader"]

    ultra_pool = unique(
        capabilities.get("ultra_pool", [])
    )

    super_pool = unique(
        capabilities.get("super_pool", [])
    )

    if not ultra_pool:
        raise RuntimeError(
            "No Nemotron Ultra connections available."
        )

    if not super_pool:
        raise RuntimeError(
            "No Nemotron Super connections available."
        )

    # The capability audit is the source of truth for
    # which OpenRouter connections actually support each model.
    if set(ultra_pool) != set(
        leader_role["model_strategy"]["primary"]["pool"]
    ):
        raise RuntimeError(
            "Ultra capability pool does not match roles.json."
        )

    if set(super_pool) != set(
        leader_role["model_strategy"]["failover"]["pool"]
    ):
        raise RuntimeError(
            "Super capability pool does not match roles.json."
        )

    profiles = {
        "version": 2,

        "architecture": {
            "provider": "openrouter",

            "strategy": (
                "model-aware-primary-failover"
            ),

            "primary_model": PRIMARY_MODEL,
            "failover_model": FAILOVER_MODEL,

            "safe_stop_on_exhaustion": True,
        },

        "pools": {
            "primary": {
                "provider": "openrouter",
                "model": PRIMARY_MODEL,
                "connections": ultra_pool,
            },

            "failover": {
                "provider": "openrouter",
                "model": FAILOVER_MODEL,
                "connections": super_pool,
            },
        },

        "runtime": {
            "active_tier": "primary",
            "active_connection": ultra_pool[0],
            "active_model": PRIMARY_MODEL,

            "primary_index": 0,
            "failover_index": 0,

            "state": "READY",

            "failure_history": [],
        },
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            profiles,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("=" * 70)
    print("LEADER PROFILES INITIALIZED")
    print("=" * 70)

    print()
    print("PRIMARY TIER")
    print(f"  Model       : {PRIMARY_MODEL}")
    print(f"  Connections : {len(ultra_pool)}")
    print(f"  Active      : {ultra_pool[0]}")

    print()
    print("FAILOVER TIER")
    print(f"  Model       : {FAILOVER_MODEL}")
    print(f"  Connections : {len(super_pool)}")

    print()
    print("RUNTIME")
    print("  State       : READY")
    print("  Active tier : primary")
    print(f"  Active conn : {ultra_pool[0]}")

    print()
    print(
        "Safe stop on full leadership exhaustion: ENABLED"
    )

    print()
    print(f"Saved: {OUTPUT_FILE.name}")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())