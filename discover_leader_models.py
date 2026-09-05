from __future__ import annotations

import json
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent
KEY_FILE = BASE_DIR / "openrouter_keys.txt"
OUTPUT_FILE = BASE_DIR / "leader_capabilities.json"

MODELS_URL = "https://openrouter.ai/api/v1/models"
TIMEOUT = 20

ULTRA = "nvidia/nemotron-3-ultra-550b-a55b:free"
SUPER = "nvidia/nemotron-3-super-120b-a12b:free"


def read_keys(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)

    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def check_models(key: str) -> tuple[bool, list[str], str | None]:
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    try:
        response = requests.get(
            MODELS_URL,
            headers=headers,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, [], type(exc).__name__

    if response.status_code != 200:
        return False, [], f"HTTP_{response.status_code}"

    try:
        data = response.json()
    except ValueError:
        return False, [], "INVALID_JSON"

    models = data.get("data", [])

    if not isinstance(models, list):
        return False, [], "INVALID_MODEL_LIST"

    model_ids = {
        item.get("id")
        for item in models
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    found = []

    if ULTRA in model_ids:
        found.append(ULTRA)

    if SUPER in model_ids:
        found.append(SUPER)

    return True, found, None


def main() -> int:
    keys = read_keys(KEY_FILE)

    print("=" * 70)
    print("OPENROUTER LEADER MODEL DISCOVERY")
    print("=" * 70)
    print(f"Connections found: {len(keys)}")
    print()

    results = {}

    ultra_pool = []
    super_pool = []

    for index, key in enumerate(keys, start=1):
        connection_id = f"OR-{index:02d}"

        ok, models, error = check_models(key)

        result = {
            "connection_id": connection_id,
            "provider": "openrouter",
            "models": models,
            "catalog_check": "OK" if ok else "FAILED",
            "error": error,
            "role": None,
        }

        results[connection_id] = result

        if not ok:
            print(
                f"{connection_id:<8} "
                f"CATALOG FAILED ({error})"
            )
            continue

        print(f"{connection_id:<8} OK")

        if ULTRA in models:
            ultra_pool.append(connection_id)
            print("         Ultra : AVAILABLE")

        if SUPER in models:
            super_pool.append(connection_id)
            print("         Super : AVAILABLE")

        if not models:
            print("         Leadership models: NONE")

    output = {
        "version": 1,
        "primary_model": ULTRA,
        "secondary_model": SUPER,
        "ultra_pool": ultra_pool,
        "super_pool": super_pool,
        "connections": results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 70)
    print("LEADER MODEL POOLS")
    print("=" * 70)

    print(
        f"Ultra pool ({len(ultra_pool)}): "
        f"{', '.join(ultra_pool) if ultra_pool else 'NONE'}"
    )

    print(
        f"Super pool ({len(super_pool)}): "
        f"{', '.join(super_pool) if super_pool else 'NONE'}"
    )

    print()
    print(f"Saved: {OUTPUT_FILE.name}")
    print()
    print("No inference requests were sent.")
    print("No roles.json changes were made.")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())