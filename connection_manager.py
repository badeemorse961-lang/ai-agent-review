from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from protected_secret_store import SecretStore, WindowsProtectedSecretStore

BASE_DIR = Path(__file__).resolve().parent
REGISTRY_FILE = BASE_DIR / "connections.json"
AUTHORITATIVE_REGISTRY_FILE = BASE_DIR / "config" / "registry.json"
ROLE_SOURCE = "config/registry.json"
SECRET_DIR_ENV = "AI_AGENT_SECRET_DIR"
DEFAULT_SECRET_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local")) / "AI-Agent" / "import-sources"

PROVIDER_FILES = {"groq": "groq_keys.txt", "openrouter": "openrouter_keys.txt"}
PROVIDER_PREFIXES = {"groq": "GROQ", "openrouter": "OR"}
LIFECYCLE_ACTIVE = "ACTIVE"
LIFECYCLE_DISABLED = "DISABLED"
LIFECYCLE_FAILED = "FAILED"
LIFECYCLE_INVALID = "INVALID"
LIFECYCLE_REMOVED = "REMOVED"
LIFECYCLE_VALUES = {LIFECYCLE_ACTIVE, LIFECYCLE_DISABLED, LIFECYCLE_FAILED, LIFECYCLE_INVALID, LIFECYCLE_REMOVED}
NON_ELIGIBLE = {LIFECYCLE_DISABLED, LIFECYCLE_FAILED, LIFECYCLE_INVALID, LIFECYCLE_REMOVED}


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
    if provider not in PROVIDER_FILES:
        raise ValueError(f"Unsupported provider: {provider}")
    return secret_dir() / PROVIDER_FILES[provider]


def resolve_secret_file(provider: str) -> Path:
    """Resolve only an external TXT import source; it is never credential persistence."""
    path = secret_file(provider)
    if not path.exists():
        raise FileNotFoundError(f"Import source not found: {path}")
    return path


def load_registry() -> dict:
    if not REGISTRY_FILE.exists():
        return {"version": 2, "role_source": ROLE_SOURCE, "connections": {}}
    data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("connections"), dict):
        raise ValueError("Connection registry must contain a 'connections' object")
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
    values = [
        connection_id for connection_id, item in registry.get("connections", {}).items()
        if isinstance(item, dict) and item.get("provider") == provider
    ]
    return sorted(values, key=lambda value: int(value.split("-", 1)[1]))


def _next_connection_id(used_ids: set[str], prefix: str) -> str:
    number = 1
    while f"{prefix}-{number:02d}" in used_ids:
        number += 1
    return f"{prefix}-{number:02d}"


def _status(item: dict[str, Any]) -> str:
    raw = str(item.get("status", ""))
    if raw == "VALIDATED":
        return LIFECYCLE_ACTIVE
    if raw == "KEY_ROTATED":
        return LIFECYCLE_DISABLED
    if raw in LIFECYCLE_VALUES:
        return raw
    return LIFECYCLE_DISABLED


def _set_rotation_pending(item: dict[str, Any], previous_status: str) -> None:
    item["status"] = LIFECYCLE_DISABLED
    item["active"] = False
    item["credential_validated"] = False
    item["validation_required"] = True
    item.pop("failure_reason", None)
    if previous_status in {LIFECYCLE_FAILED, LIFECYCLE_INVALID}:
        item["failure_reason"] = "credential replaced; successful provider validation is required"


def import_provider(provider: str, keys_path: Path, registry: dict, prefix: str, *, secret_store: SecretStore | None = None, persist: bool = True) -> ImportSummary:
    """Additive import into protected storage; TXT omission never removes a prior connection."""
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
        if isinstance(item, dict) and item.get("provider") == provider
        and item.get("status") != LIFECYCLE_REMOVED
        and isinstance(item.get("key_fingerprint"), str)
    }
    used_ids = {connection_id for connection_id, item in connections.items() if isinstance(item, dict) and item.get("provider") == provider}
    imported = already_present = rejected = 0
    touched: list[str] = []
    seen: set[str] = set()

    def ingest(connection_id: str, secret: str) -> None:
        nonlocal imported, already_present, rejected
        fp = fingerprint(secret)
        if fp in seen:
            already_present += 1
            return
        seen.add(fp)
        duplicate_id = by_fingerprint.get(fp)
        if duplicate_id is not None and duplicate_id != connection_id:
            already_present += 1
            return
        existing = connections.get(connection_id)
        if existing is None:
            connections[connection_id] = {
                "connection_id": connection_id,
                "provider": provider,
                "key_fingerprint": fp,
                "role": None,
                "status": LIFECYCLE_DISABLED,
                "active": False,
                "credential_validated": False,
                "validation_required": True,
            }
            store.put(connection_id, provider, secret, fp)
            by_fingerprint[fp] = connection_id
            imported += 1
            touched.append(connection_id)
            return
        if not isinstance(existing, dict) or existing.get("provider") != provider:
            rejected += 1
            return
        if existing.get("status") == LIFECYCLE_REMOVED:
            rejected += 1
            return
        current_fp = existing.get("key_fingerprint")
        if current_fp == fp:
            if store.has(connection_id):
                already_present += 1
            else:
                store.put(connection_id, provider, secret, fp)
                _set_rotation_pending(existing, _status(existing))
                existing["key_fingerprint"] = fp
                imported += 1
                touched.append(connection_id)
            return
        previous_status = _status(existing)
        store.put(connection_id, provider, secret, fp)
        existing["key_fingerprint"] = fp
        _set_rotation_pending(existing, previous_status)
        if current_fp:
            by_fingerprint.pop(current_fp, None)
        by_fingerprint[fp] = connection_id
        imported += 1
        touched.append(connection_id)

    for connection_id, secret in labeled.items():
        ingest(connection_id, secret)
    for secret in unlabeled:
        fp = fingerprint(secret)
        existing_id = by_fingerprint.get(fp)
        if existing_id is not None:
            ingest(existing_id, secret)
            continue
        connection_id = _next_connection_id(used_ids | set(connections), prefix)
        used_ids.add(connection_id)
        ingest(connection_id, secret)

    if persist:
        save_registry(registry)
    return ImportSummary(provider, imported, already_present, rejected, "PERSISTED" if persist else "TEST_ONLY", tuple(touched))


def replace_connection_credential(connection_id: str, keys_path: Path, registry: dict, *, secret_store: SecretStore, persist: bool = True) -> ImportSummary:
    """Replace one credential by an explicitly selected stable connection ID."""
    item = registry.get("connections", {}).get(connection_id)
    if not isinstance(item, dict):
        raise KeyError(f"Connection not found: {connection_id}")
    provider = item.get("provider")
    if provider not in PROVIDER_FILES:
        raise ValueError(f"Unsupported provider: {provider}")
    if keys_path.suffix.lower() != ".txt":
        raise ValueError("Replacement source must be a .txt file")
    labeled, unlabeled = read_secret_source(keys_path, PROVIDER_PREFIXES[provider])
    if unlabeled or set(labeled) != {connection_id}:
        raise ValueError(f"Replacement TXT must contain exactly one labeled entry for {connection_id}")
    if item.get("status") == LIFECYCLE_REMOVED:
        raise ValueError(f"Connection has been removed: {connection_id}")
    secret = labeled[connection_id]
    fp = fingerprint(secret)
    for other_id, other in registry.get("connections", {}).items():
        if other_id == connection_id or not isinstance(other, dict):
            continue
        if other.get("provider") == provider and other.get("status") != LIFECYCLE_REMOVED and other.get("key_fingerprint") == fp:
            raise ValueError(f"Credential fingerprint already belongs to {other_id}")
    current_fp = item.get("key_fingerprint")
    if current_fp == fp and secret_store.has(connection_id):
        return ImportSummary(provider, 0, 1, 0, "PERSISTED" if persist else "TEST_ONLY", (connection_id,))
    secret_store.put(connection_id, provider, secret, fp)
    item["key_fingerprint"] = fp
    _set_rotation_pending(item, _status(item))
    if persist:
        save_registry(registry)
    return ImportSummary(provider, 1, 0, 0, "PERSISTED" if persist else "TEST_ONLY", (connection_id,))


def _assigned_connections(authoritative: dict) -> set[str]:
    ids: set[str] = set()
    architecture = authoritative.get("architecture", {})
    leader = architecture.get("leader", {}) if isinstance(architecture, dict) else {}
    if isinstance(leader, dict):
        for key in ("primary_pool", "failover_pool"):
            ids.update(item for item in leader.get(key, []) if isinstance(item, str))
    workers = architecture.get("workers", {}) if isinstance(architecture, dict) else {}
    roles = workers.get("roles", {}) if isinstance(workers, dict) else {}
    if isinstance(roles, dict):
        for values in roles.values():
            if isinstance(values, list):
                ids.update(item for item in values if isinstance(item, str))
    return ids


def get_connection_status(connection_id: str, registry: dict | None = None) -> str:
    data = registry or load_registry()
    item = data.get("connections", {}).get(connection_id)
    return _status(item) if isinstance(item, dict) else LIFECYCLE_REMOVED


def set_connection_status(connection_id: str, status: str, registry: dict | None = None, *, persist: bool = True) -> dict[str, Any]:
    if status not in LIFECYCLE_VALUES:
        raise ValueError(f"Unsupported connection lifecycle status: {status}")
    data = registry or load_registry()
    item = data.get("connections", {}).get(connection_id)
    if not isinstance(item, dict):
        raise KeyError(f"Connection not found: {connection_id}")
    if status == LIFECYCLE_ACTIVE:
        authoritative = json.loads(AUTHORITATIVE_REGISTRY_FILE.read_text(encoding="utf-8"))
        if connection_id not in _assigned_connections(authoritative):
            raise ValueError("Connection must be assigned in config/registry.json before it can be enabled")
        if item.get("credential_validated") is False or item.get("validation_required") is True:
            raise ValueError("Successful credential validation is required before activation")
        if item.get("status") in {LIFECYCLE_FAILED, LIFECYCLE_INVALID, LIFECYCLE_REMOVED}:
            raise ValueError("Failed or removed connection cannot be enabled without successful validation")
    item["status"] = status
    item["active"] = status == LIFECYCLE_ACTIVE
    if status == LIFECYCLE_DISABLED:
        item["validation_required"] = False
    if status in {LIFECYCLE_FAILED, LIFECYCLE_INVALID}:
        item["credential_validated"] = False
        item["validation_required"] = True
        if "failure_reason" not in item:
            item["failure_reason"] = "runtime validation reported the connection as unavailable"
    if persist:
        save_registry(data)
    return item


def disable_connection(connection_id: str, registry: dict | None = None, *, persist: bool = True) -> dict[str, Any]:
    return set_connection_status(connection_id, LIFECYCLE_DISABLED, registry, persist=persist)


def enable_connection(connection_id: str, registry: dict | None = None, *, persist: bool = True) -> dict[str, Any]:
    return set_connection_status(connection_id, LIFECYCLE_ACTIVE, registry, persist=persist)


def mark_connection_failed(connection_id: str, *, invalid: bool = False, reason: str | None = None, registry: dict | None = None, persist: bool = True) -> dict[str, Any]:
    item = set_connection_status(connection_id, LIFECYCLE_INVALID if invalid else LIFECYCLE_FAILED, registry, persist=persist)
    if reason:
        data = registry or load_registry()
        item["failure_reason"] = reason[:240]
        if persist:
            save_registry(data)
    return item


def validate_connection(connection_id: str, *, registry: dict | None = None, secret_store: SecretStore | None = None, validator: Any | None = None, persist: bool = True) -> dict[str, Any]:
    """Provider-validate a credential, then activate an assigned connection only after success."""
    data = registry or load_registry()
    item = data.get("connections", {}).get(connection_id)
    if not isinstance(item, dict):
        raise KeyError(f"Connection not found: {connection_id}")
    if item.get("status") == LIFECYCLE_REMOVED:
        raise ValueError(f"Connection has been removed: {connection_id}")
    store = secret_store or WindowsProtectedSecretStore()
    provider = item.get("provider")
    if not isinstance(provider, str):
        raise ValueError("Connection provider is invalid")
    secret = store.get(connection_id, provider)
    expected_fp = item.get("key_fingerprint")
    actual_fp = fingerprint(secret)
    if expected_fp != actual_fp:
        raise ValueError("Protected credential fingerprint does not match connection metadata")
    check = validator or _default_credential_validator
    check(provider, connection_id, store)
    authoritative = json.loads(AUTHORITATIVE_REGISTRY_FILE.read_text(encoding="utf-8"))
    assigned = connection_id in _assigned_connections(authoritative)
    item["credential_validated"] = True
    item["validation_required"] = False
    item.pop("failure_reason", None)
    if assigned and item.get("status") in {LIFECYCLE_FAILED, LIFECYCLE_INVALID, LIFECYCLE_DISABLED, "VALIDATED"}:
        item["status"] = LIFECYCLE_ACTIVE
        item["active"] = True
    elif not assigned:
        item["status"] = LIFECYCLE_DISABLED
        item["active"] = False
    if persist:
        save_registry(data)
    return item


def _default_credential_validator(provider: str, connection_id: str, store: SecretStore) -> None:
    from provider_transport import OpenAICompatibleTransport
    OpenAICompatibleTransport(secret_store=store).validate_connection(provider=provider, account_id=connection_id)


def remove_connection(connection_id: str, *, registry: dict | None = None, secret_store: SecretStore | None = None, persist: bool = True) -> bool:
    data = registry or load_registry()
    item = data.get("connections", {}).get(connection_id)
    if not isinstance(item, dict):
        raise KeyError(f"Connection not found: {connection_id}")
    authoritative = json.loads(AUTHORITATIVE_REGISTRY_FILE.read_text(encoding="utf-8"))
    if connection_id in _assigned_connections(authoritative):
        raise ValueError("Assigned connection cannot be removed from Control Center; update routing through the approved Core configuration authority first")
    store = secret_store or WindowsProtectedSecretStore()
    store.delete(connection_id)
    item["status"] = LIFECYCLE_REMOVED
    item["active"] = False
    item["credential_validated"] = False
    item["validation_required"] = False
    if persist:
        save_registry(data)
    return True


def connection_is_eligible(connection_id: str, registry: dict | None = None) -> bool:
    data = registry or load_registry()
    item = data.get("connections", {}).get(connection_id)
    if not isinstance(item, dict):
        return False
    return (
        _status(item) not in NON_ELIGIBLE
        and item.get("active") is True
        and item.get("credential_validated", True) is True
        and item.get("validation_required", False) is False
    )


def get_secret(connection_id: str, provider: str | None = None, *, secret_store: SecretStore | None = None) -> str:
    return (secret_store or WindowsProtectedSecretStore()).get(connection_id, provider)


def main() -> int:
    registry = load_registry()
    print("Connection metadata registry loaded.")
    print("Protected secret store: Windows user-scoped DPAPI")
    print("TXT import semantics : ADDITIVE")
    print("Raw secrets printed  : NO")
    print(f"Groq connections     : {len(_connection_ids_for_provider(registry, 'groq'))}")
    print(f"OpenRouter connections: {len(_connection_ids_for_provider(registry, 'openrouter'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
