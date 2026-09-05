from __future__ import annotations

import hashlib
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
GROQ_FILE = BASE_DIR / "groq_keys.txt"
OPENROUTER_FILE = BASE_DIR / "openrouter_keys.txt"
REGISTRY_FILE = BASE_DIR / "connections.json"


def read_keys(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)

    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def load_registry() -> dict:
    if not REGISTRY_FILE.exists():
        return {"version": 1, "connections": {}}

    return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))


def save_registry(data: dict) -> None:
    REGISTRY_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def import_provider(
    provider: str,
    keys: list[str],
    registry: dict,
    prefix: str,
) -> None:
    connections = registry["connections"]

    for index, key in enumerate(keys, start=1):
        connection_id = f"{prefix}-{index:02d}"
        fp = fingerprint(key)

        existing = connections.get(connection_id)

        if existing is None:
            connections[connection_id] = {
                "connection_id": connection_id,
                "provider": provider,
                "key_fingerprint": fp,
                "role": None,
                "status": "VALIDATED",
                "active": False,
            }
        else:
            # Same connection_id, possibly a rotated key.
            if existing.get("key_fingerprint") != fp:
                existing["key_fingerprint"] = fp
                existing["status"] = "KEY_ROTATED"
                existing["active"] = False


def main() -> int:
    groq_keys = read_keys(GROQ_FILE)
    openrouter_keys = read_keys(OPENROUTER_FILE)

    registry = load_registry()

    import_provider(
        provider="groq",
        keys=groq_keys,
        registry=registry,
        prefix="GROQ",
    )

    import_provider(
        provider="openrouter",
        keys=openrouter_keys,
        registry=registry,
        prefix="OR",
    )

    save_registry(registry)

    print("Connection registry updated.")
    print(f"Groq connections      : {len(groq_keys)}")
    print(f"OpenRouter connections: {len(openrouter_keys)}")
    print(f"Registry              : {REGISTRY_FILE.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())