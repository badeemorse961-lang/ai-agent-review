from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable


BASE_DIR = Path(__file__).resolve().parent
REGISTRY_FILE = BASE_DIR / "connections.json"
ROLE_SOURCE = "config/registry.json"
SECRET_DIR_ENV = "AI_AGENT_SECRET_DIR"
LEGACY_SECRET_FALLBACK_ENV = "AI_AGENT_ALLOW_LEGACY_SECRET_PATH"
DEFAULT_SECRET_DIR = Path(
    os.environ.get("LOCALAPPDATA", Path.home() / ".local")
) / "AI-Agent" / "secrets"

PROVIDER_FILES = {
    "groq": "groq_keys.txt",
    "openrouter": "openrouter_keys.txt",
}
PROVIDER_PREFIXES = {
    "groq": "GROQ",
    "openrouter": "OR",
}


def fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def secret_dir() -> Path:
    configured = os.environ.get(SECRET_DIR_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_SECRET_DIR


def secret_file(provider: str) -> Path:
    try:
        filename = PROVIDER_FILES[provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported provider: {provider}") from exc
    return secret_dir() / filename


def _legacy_secret_file(provider: str) -> Path:
    try:
        return BASE_DIR / PROVIDER_FILES[provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported provider: {provider}") from exc


def resolve_secret_file(provider: str) -> Path:
    """Resolve the external secret file; legacy repo-relative use is opt-in only."""
    external = secret_file(provider)
    if external.exists():
        return external

    legacy = _legacy_secret_file(provider)
    allow_legacy = os.environ.get(LEGACY_SECRET_FALLBACK_ENV, "").strip().lower()
    if allow_legacy in {"1", "true", "yes"} and legacy.exists():
        return legacy

    raise FileNotFoundError(
        f"Secret file not found outside repository: {external}. "
        f"Set {SECRET_DIR_ENV} to the protected external secret directory. "
        f"Legacy repo-relative fallback requires {LEGACY_SECRET_FALLBACK_ENV}=1."
    )


def load_registry() -> dict:
    if not REGISTRY_FILE.exists():
        return {"version": 2, "role_source": ROLE_SOURCE, "connections": {}}

    data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Connection registry root must be an object")
    connections = data.get("connections")
    if not isinstance(connections, dict):
        raise ValueError("Connection registry must contain an object named 'connections'")
    data["role_source"] = ROLE_SOURCE
    return data


def save_registry(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("Connection registry root must be an object")
    data["role_source"] = ROLE_SOURCE
    REGISTRY_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _parse_secret_lines(lines: Iterable[str], prefix: str) -> tuple[dict[str, str], list[str]]:
    """Parse canonical ID=secret lines plus legacy unlabeled secret lines."""
    labeled: dict[str, str] = {}
    unlabeled: list[str] = []

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if "=" in line:
            connection_id, secret = line.split("=", 1)
            connection_id = connection_id.strip()
            secret = secret.strip()
            if not connection_id or not secret:
                raise ValueError("Secret mapping contains an empty connection ID or secret")
            if not connection_id.startswith(f"{prefix}-"):
                raise ValueError(
                    f"Connection ID {connection_id!r} does not belong to provider prefix {prefix}"
                )
            try:
                number = int(connection_id.split("-", 1)[1])
            except (IndexError, ValueError) as exc:
                raise ValueError(f"Invalid connection ID: {connection_id}") from exc
            if number <= 0:
                raise ValueError(f"Invalid connection ID: {connection_id}")
            if connection_id in labeled:
                raise ValueError(f"Duplicate connection ID in secret file: {connection_id}")
            labeled[connection_id] = secret
        else:
            unlabeled.append(line)

    return labeled, unlabeled


def read_secret_source(path: Path, prefix: str) -> tuple[dict[str, str], list[str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    return _parse_secret_lines(path.read_text(encoding="utf-8").splitlines(), prefix)


def _connection_ids_for_provider(registry: dict, provider: str) -> list[str]:
    connections = registry["connections"]
    return sorted(
        (
            connection_id
            for connection_id, item in connections.items()
            if isinstance(item, dict) and item.get("provider") == provider
        ),
        key=lambda value: int(value.split("-", 1)[1]),
    )


def _next_connection_id(used_ids: set[str], prefix: str) -> str:
    number = 1
    while f"{prefix}-{number:02d}" in used_ids:
        number += 1
    return f"{prefix}-{number:02d}"


def import_provider(
    provider: str,
    keys_path: Path,
    registry: dict,
    prefix: str,
) -> None:
    connections = registry.setdefault("connections", {})
    labeled, unlabeled = read_secret_source(keys_path, prefix)

    by_fingerprint = {
        item.get("key_fingerprint"): connection_id
        for connection_id, item in connections.items()
        if isinstance(item, dict)
        and item.get("provider") == provider
        and isinstance(item.get("key_fingerprint"), str)
    }

    used_ids = {
        connection_id
        for connection_id, item in connections.items()
        if isinstance(item, dict) and item.get("provider") == provider
    }
    assigned_ids: set[str] = set()
    assigned_fingerprints: set[str] = set()

    def upsert(connection_id: str, secret: str) -> None:
        fp = fingerprint(secret)
        if fp in assigned_fingerprints:
            raise ValueError(f"The same secret is assigned more than once for {provider}: {connection_id}")
        assigned_fingerprints.add(fp)
        assigned_ids.add(connection_id)

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
            return

        if existing.get("provider") != provider:
            raise ValueError(
                f"Connection {connection_id} already belongs to another provider"
            )

        if existing.get("key_fingerprint") != fp:
            existing["key_fingerprint"] = fp
            existing["status"] = "KEY_ROTATED"
            existing["active"] = False
        else:
            existing["status"] = "VALIDATED"

    for connection_id, secret in labeled.items():
        upsert(connection_id, secret)

    for secret in unlabeled:
        fp = fingerprint(secret)
        existing_id = by_fingerprint.get(fp)
        if existing_id is not None and existing_id not in assigned_ids:
            upsert(existing_id, secret)
            continue

        connection_id = _next_connection_id(used_ids | assigned_ids, prefix)
        upsert(connection_id, secret)

    stale_ids = used_ids - assigned_ids
    for connection_id in stale_ids:
        item = connections.get(connection_id)
        if isinstance(item, dict) and item.get("provider") == provider:
            item["status"] = "NOT_PRESENT_IN_SECRET_SOURCE"
            item["active"] = False


def main() -> int:
    registry = load_registry()

    resolved_files: dict[str, Path] = {}
    for provider in PROVIDER_FILES:
        resolved_files[provider] = resolve_secret_file(provider)
        import_provider(
            provider=provider,
            keys_path=resolved_files[provider],
            registry=registry,
            prefix=PROVIDER_PREFIXES[provider],
        )

    registry["version"] = max(int(registry.get("version", 1)), 3)
    save_registry(registry)

    counts = {
        provider: len(_connection_ids_for_provider(registry, provider))
        for provider in PROVIDER_FILES
    }

    print("Connection registry updated.")
    print(f"Secret directory       : {secret_dir()}")
    print(f"Groq connections       : {counts['groq']}")
    print(f"OpenRouter connections : {counts['openrouter']}")
    print(f"Registry               : {REGISTRY_FILE.name}")
    print("Role source            : config/registry.json")
    print("Raw secrets printed    : NO")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
