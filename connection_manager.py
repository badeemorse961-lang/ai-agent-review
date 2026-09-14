from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
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

# This is the single configuration authority for external provider secret sources.
PROVIDER_FILES = {
    "groq": "groq_keys.txt",
    "openrouter": "openrouter_keys.txt",
}
PROVIDER_PREFIXES = {
    "groq": "GROQ",
    "openrouter": "OR",
}


@dataclass(frozen=True)
class SecretSourceSyncResult:
    """Secret-free evidence for one provider source synchronization."""

    provider: str
    source_exists: bool
    lines_read: int
    unique_candidates: int
    duplicate_candidates: int
    already_known: int
    newly_imported: int
    invalid: int
    failed: int
    source_path: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


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
    """Import keys into connection metadata without destructive source reconciliation."""
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
            raise ValueError(
                f"The same secret is assigned more than once for {provider}: {connection_id}"
            )
        assigned_fingerprints.add(fp)
        assigned_ids.add(connection_id)

        existing = connections.get(connection_id)
        if existing is None:
            connections[connection_id] = {
                "connection_id": connection_id,
                "provider": provider,
                "key_fingerprint": fp,
                "role": None,
                "status": "PENDING_ASSIGNMENT",
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
        elif existing.get("status") == "PENDING_ASSIGNMENT":
            existing["status"] = "PENDING_ASSIGNMENT"

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


def _parse_startup_source(path: Path) -> tuple[list[str], int, int]:
    """Parse canonical one-secret-per-line source without logging values."""
    candidates: list[str] = []
    invalid = 0
    duplicate_candidates = 0
    seen: set[str] = set()

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if any(character.isspace() for character in line):
            invalid += 1
            continue
        if line in seen:
            duplicate_candidates += 1
            continue
        seen.add(line)
        candidates.append(line)

    return candidates, invalid, duplicate_candidates


def sync_external_secret_sources() -> dict[str, dict[str, object]]:
    """Synchronize external provider secret sources additively and idempotently.

    The TXT files are secret sources, not deletion manifests. Existing connection
    metadata is never removed or deactivated because a source line is absent.
    New connections remain PENDING_ASSIGNMENT until the authoritative registry has
    an explicit assignment; no role/model is guessed by this function.
    """
    registry = load_registry()
    results: dict[str, dict[str, object]] = {}
    changed = False

    for provider, filename in PROVIDER_FILES.items():
        source = secret_dir() / filename
        base = {
            "provider": provider,
            "source_exists": source.exists(),
            "lines_read": 0,
            "unique_candidates": 0,
            "duplicate_candidates": 0,
            "already_known": 0,
            "newly_imported": 0,
            "invalid": 0,
            "failed": 0,
            "source_path": str(source),
        }

        if not source.exists():
            results[provider] = base
            continue

        try:
            lines = source.read_text(encoding="utf-8").splitlines()
            base["lines_read"] = len(lines)
            candidates: list[str] = []
            seen: set[str] = set()
            for raw in lines:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if any(character.isspace() for character in line):
                    base["invalid"] += 1
                    continue
                if line in seen:
                    base["duplicate_candidates"] += 1
                    continue
                seen.add(line)
                candidates.append(line)

            base["unique_candidates"] = len(candidates)
            connections = registry.setdefault("connections", {})
            known = {
                item.get("key_fingerprint")
                for item in connections.values()
                if isinstance(item, dict)
                and item.get("provider") == provider
                and isinstance(item.get("key_fingerprint"), str)
            }
            used_ids = {
                connection_id
                for connection_id, item in connections.items()
                if isinstance(item, dict) and item.get("provider") == provider
            }
            for secret in candidates:
                fp = fingerprint(secret)
                if fp in known:
                    base["already_known"] += 1
                    continue
                connection_id = _next_connection_id(used_ids, PROVIDER_PREFIXES[provider])
                connections[connection_id] = {
                    "connection_id": connection_id,
                    "provider": provider,
                    "key_fingerprint": fp,
                    "role": None,
                    "status": "PENDING_ASSIGNMENT",
                    "active": False,
                }
                used_ids.add(connection_id)
                known.add(fp)
                base["newly_imported"] += 1
                changed = True
        except (OSError, UnicodeError):
            base["failed"] = 1

        results[provider] = base

    if changed:
        save_registry(registry)

    return results


def main() -> int:
    results = sync_external_secret_sources()
    print("External secret source sync complete.")
    print(f"Secret directory       : {secret_dir()}")
    for provider in PROVIDER_FILES:
        result = results[provider]
        print(f"{provider} source exists : {result['source_exists']}")
        print(f"{provider} lines read    : {result['lines_read']}")
        print(f"{provider} unique        : {result['unique_candidates']}")
        print(f"{provider} duplicates    : {result['duplicate_candidates']}")
        print(f"{provider} known         : {result['already_known']}")
        print(f"{provider} imported      : {result['newly_imported']}")
        print(f"{provider} invalid       : {result['invalid']}")
        print(f"{provider} failed        : {result['failed']}")
    print("Raw secrets printed    : NO")
    print("Legacy repo fallback   : NOT USED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
