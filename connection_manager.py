from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Any

from protected_secret_store import SecretStore, WindowsProtectedSecretStore


BASE_DIR = Path(__file__).resolve().parent
REGISTRY_FILE = BASE_DIR / "connections.json"
ROLE_SOURCE = "config/registry.json"
SECRET_DIR_ENV = "AI_AGENT_SECRET_DIR"
LEGACY_SECRET_FALLBACK_ENV = "AI_AGENT_ALLOW_LEGACY_SECRET_PATH"
DEFAULT_SECRET_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local")) / "AI-Agent" / "secrets"

PROVIDER_FILES = {
    "groq": "groq_keys.txt",
    "openrouter": "openrouter_keys.txt",
}
PROVIDER_PREFIXES = {
    "groq": "GROQ",
    "openrouter": "OR",
}
LIFECYCLE_ACTIVE = "ACTIVE"
LIFECYCLE_DISABLED = "DISABLED"
LIFECYCLE_FAILED = "FAILED"
LIFECYCLE_INVALID = "INVALID"
LIFECYCLE_REMOVED = "REMOVED"
LIFECYCLE_VALUES = {
    LIFECYCLE_ACTIVE,
    LIFECYCLE_DISABLED,
    LIFECYCLE_FAILED,
    LIFECYCLE_INVALID,
    LIFECYCLE_REMOVED,
}


@dataclass(frozen=True)
class ImportSummary:
    provider: str
    imported_count: int
    already_present_count: int
    rejected_count: int
    persistence_status: str
    connection_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "imported_count": self.imported_count,
            "already_present_count": self.already_present_count,
            "rejected_count": self.rejected_count,
            "persistence_status": self.persistence_status,
            "connection_ids": list(self.connection_ids),
            "raw_secrets_returned": False,
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
    """Resolve a TXT import source; it is never used as persistent secret storage."""
    external = secret_file(provider)
    if external.exists():
        return external

    legacy = _legacy_secret_file(provider)
    allow_legacy = os.environ.get(LEGACY_SECRET_FALLBACK_ENV, "").strip().lower()
    if allow_legacy in {"1", "true", "yes"} and legacy.exists():
        return legacy

    raise FileNotFoundError(
        f"Import source not found outside repository: {external}. "
        f"Set {SECRET_DIR_ENV} to the protected import-source directory. "
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
    REGISTRY_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _parse_secret_lines(lines: Iterable[str], prefix: str) -> tuple[dict[str, str], list[str]]:
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
                raise ValueError(f"Connection ID {connection_id!r} does not belong to provider prefix {prefix}")
            try:
                number = int(connection_id.split("-", 1)[1])
            except (IndexError, ValueError) as exc:
                raise ValueError(f"Invalid connection ID: {connection_id}") from exc
            if number <= 0:
                raise ValueError(f"Invalid connection ID: {connection_id}")
            if connection_id in labeled:
                raise ValueError(f"Duplicate connection ID in import source: {connection_id}")
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
    values = [
        connection_id
        for connection_id, item in connections.items()
        if isinstance(item, dict) and item.get("provider") == provider
    ]
    return sorted(values, key=lambda value: int(value.split("-", 1)[1]))


def _next_connection_id(used_ids: set[str], prefix: str) -> str:
    number = 1
    while f"{prefix}-{number:02d}" in used_ids:
        number += 1
    return f"{prefix}-{number:02d}"


def _normalize_status(item: dict[str, Any]) -> str:
    status = str(item.get("status", ""))
    if status == "VALIDATED":
        return LIFECYCLE_ACTIVE if bool(item.get("active")) else LIFECYCLE_DISABLED
    if status == "KEY_ROTATED":
        return LIFECYCLE_DISABLED
    if status in LIFECYCLE_VALUES:
        return status
    return LIFECYCLE_DISABLED


def _metadata_status(item: dict[str, Any]) -> str:
    status = _normalize_status(item)
    item["status"] = status
    item["active"] = status == LIFECYCLE_ACTIVE
    return status


def _default_connection(connection_id: str, provider: str, fp: str) -> dict[str, Any]:
    return {
        "connection_id": connection_id,
        "provider": provider,
        "key_fingerprint": fp,
        "role": None,
        "status": LIFECYCLE_DISABLED,
        "active": False,
    }


def import_provider(
    provider: str,
    keys_path: Path,
    registry: dict,
    prefix: str,
    *,
    secret_store: SecretStore | None = None,
) -> ImportSummary:
    """Additively import secrets into protected storage; never remove by omission."""
    if provider not in PROVIDER_FILES:
        raise ValueError(f"Unsupported provider: {provider}")
    if keys_path.suffix.lower() != ".txt":
        raise ValueError("Import source must be a .txt file")

    connections = registry.setdefault("connections", {})
    store = secret_store or WindowsProtectedSecretStore()
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

    imported = 0
    already_present = 0
    rejected = 0
    touched: list[str] = []
    seen_fingerprints: set[str] = set()

    def add_secret(connection_id: str, secret: str, *, allow_rotation: bool) -> None:
        nonlocal imported, already_present, rejected
        fp = fingerprint(secret)
        if fp in seen_fingerprints:
            already_present += 1
            return
        seen_fingerprints.add(fp)

        existing_id = by_fingerprint.get(fp)
        if existing_id and existing_id != connection_id:
            already_present += 1
            return

        existing = connections.get(connection_id)
        if existing is None:
            existing = _default_connection(connection_id, provider, fp)
            connections[connection_id] = existing
            by_fingerprint[fp] = connection_id
            store.put(connection_id, provider, secret, fp)
            imported += 1
            touched.append(connection_id)
            return

        if not isinstance(existing, dict) or existing.get("provider") != provider:
            rejected += 1
            return

        current_fp = existing.get("key_fingerprint")
        if current_fp == fp:
            if not store.has(connection_id):
                store.put(connection_id, provider, secret, fp)
                imported += 1
                touched.append(connection_id)
            else:
                already_present += 1
            return

        if not allow_rotation:
            rejected += 1
            return

        old_status = _normalize_status(existing)
        store.put(connection_id, provider, secret, fp)
        existing["key_fingerprint"] = fp
        existing["status"] = old_status if old_status in {LIFECYCLE_ACTIVE, LIFECYCLE_DISABLED} else LIFECYCLE_DISABLED
        existing["active"] = existing["status"] == LIFECYCLE_ACTIVE
        by_fingerprint.pop(current_fp, None)
        by_fingerprint[fp] = connection_id
        imported += 1
        touched.append(connection_id)

    for connection_id, secret in labeled.items():
        add_secret(connection_id, secret, allow_rotation=True)

    for secret in unlabeled:
        fp = fingerprint(secret)
        existing_id = by_fingerprint.get(fp)
        if existing_id is not None:
            add_secret(existing_id, secret, allow_rotation=False)
            continue
        connection_id = _next_connection_id(used_ids | set(connections), prefix)
        used_ids.add(connection_id)
        add_secret(connection_id, secret, allow_rotation=False)

    save_registry(registry)
    return ImportSummary(
        provider=provider,
        imported_count=imported,
        already_present_count=already_present,
        rejected_count=rejected,
        persistence_status="PERSISTED",
        connection_ids=tuple(touched),
    )


def get_connection_status(connection_id: str, registry: dict | None = None) -> str:
    data = registry or load_registry()
    item = data.get("connections", {}).get(connection_id, {})
    if not isinstance(item, dict):
        return LIFECYCLE_REMOVED
    return _metadata_status(item)


def set_connection_status(connection_id: str, status: str, registry: dict | None = None) -> dict[str, Any]:
    if status not in LIFECYCLE_VALUES:
        raise ValueError(f"Unsupported connection lifecycle status: {status}")
    data = registry or load_registry()
    item = data.get("connections", {}).get(connection_id)
    if not isinstance(item, dict):
        raise KeyError(f"Connection not found: {connection_id}")
    item["status"] = status
    item["active"] = status == LIFECYCLE_ACTIVE
    save_registry(data)
    return item


def disable_connection(connection_id: str, registry: dict | None = None) -> dict[str, Any]:
    return set_connection_status(connection_id, LIFECYCLE_DISABLED, registry)


def enable_connection(connection_id: str, registry: dict | None = None) -> dict[str, Any]:
    return set_connection_status(connection_id, LIFECYCLE_ACTIVE, registry)


def mark_connection_failed(connection_id: str, *, invalid: bool = False, reason: str | None = None, registry: dict | None = None) -> dict[str, Any]:
    item = set_connection_status(connection_id, LIFECYCLE_INVALID if invalid else LIFECYCLE_FAILED, registry)
    if reason:
        item["failure_reason"] = reason[:240]
        save_registry(registry or load_registry())
    return item


def remove_connection(
    connection_id: str,
    *,
    registry: dict | None = None,
    secret_store: SecretStore | None = None,
) -> bool:
    data = registry or load_registry()
    connections = data.get("connections", {})
    item = connections.get(connection_id)
    if not isinstance(item, dict):
        raise KeyError(f"Connection not found: {connection_id}")
    store = secret_store or WindowsProtectedSecretStore()
    store.delete(connection_id)
    del connections[connection_id]
    save_registry(data)
    return True


def connection_is_eligible(connection_id: str, registry: dict | None = None) -> bool:
    data = registry or load_registry()
    item = data.get("connections", {}).get(connection_id)
    if not isinstance(item, dict):
        return False
    return _metadata_status(item) == LIFECYCLE_ACTIVE


def get_secret(connection_id: str, provider: str | None = None, *, secret_store: SecretStore | None = None) -> str:
    store = secret_store or WindowsProtectedSecretStore()
    return store.get(connection_id, provider)


def main() -> int:
    registry = load_registry()
    print("Connection metadata registry loaded.")
    print(f"Protected secret store : {secret_dir()}")
    for provider in PROVIDER_FILES:
        print(f"{provider} connections     : {len(_connection_ids_for_provider(registry, provider))}")
    print("Raw secrets printed      : NO")
    print("TXT import semantics     : ADDITIVE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
