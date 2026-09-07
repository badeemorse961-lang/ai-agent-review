from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
REGISTRY_FILE = BASE_DIR / "config" / "registry.json"
CONNECTIONS_FILE = BASE_DIR / "connections.json"
EXPECTED_ROLE_SOURCE = "config/registry.json"
NON_ELIGIBLE_STATUSES = {"DISABLED", "FAILED", "INVALID", "REMOVED"}


class RegistryError(Exception):
    """Raised when the authoritative configuration registry is invalid."""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RegistryError(f"Missing configuration file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Cannot read JSON: {path}") from exc
    if not isinstance(data, dict):
        raise RegistryError(f"JSON root must be an object: {path}")
    return data


def _unique_strings(values: Any, field: str) -> list[str]:
    if not isinstance(values, list):
        raise RegistryError(f"{field} must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise RegistryError(f"{field} contains an invalid connection id")
        if value in seen:
            raise RegistryError(f"Duplicate connection id in {field}: {value}")
        seen.add(value)
        result.append(value)
    return result


def load_registry() -> dict[str, Any]:
    return _load_json(REGISTRY_FILE)


def load_connections() -> dict[str, Any]:
    data = _load_json(CONNECTIONS_FILE)
    if data.get("role_source") != EXPECTED_ROLE_SOURCE:
        raise RegistryError("connections.json must declare config/registry.json as the authoritative role source")
    connections = data.get("connections")
    if not isinstance(connections, dict):
        raise RegistryError("connections.json must contain a 'connections' object")
    return data


def _validate_connection_metadata(connection_id: str, item: Any) -> None:
    if not isinstance(item, dict):
        raise RegistryError(f"Connection metadata must be an object: {connection_id}")
    if item.get("connection_id") != connection_id:
        raise RegistryError(f"Connection metadata ID does not match registry key: {connection_id}")
    provider = item.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise RegistryError(f"Connection provider must be a non-empty string: {connection_id}")
    digest = item.get("key_fingerprint")
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
        raise RegistryError(f"Connection key_fingerprint must be a SHA-256 hex digest: {connection_id}")
    status = item.get("status")
    if not isinstance(status, str) or not status.strip():
        raise RegistryError(f"Connection status must be a non-empty string: {connection_id}")
    active = item.get("active")
    if not isinstance(active, bool):
        raise RegistryError(f"Connection active flag must be boolean: {connection_id}")


def _status_is_eligible(item: dict[str, Any]) -> bool:
    status = str(item.get("status", ""))
    if status == "VALIDATED":
        return True
    return status not in NON_ELIGIBLE_STATUSES


def validate_registry() -> dict[str, Any]:
    registry = load_registry()
    connections_data = load_connections()
    connections = connections_data["connections"]

    architecture = registry.get("architecture")
    if not isinstance(architecture, dict):
        raise RegistryError("Registry is missing architecture")
    leader = architecture.get("leader")
    workers = architecture.get("workers")
    if not isinstance(leader, dict) or not isinstance(workers, dict):
        raise RegistryError("Registry must define leader and workers")

    leader_provider = leader.get("provider")
    worker_provider = workers.get("provider")
    if not isinstance(leader_provider, str) or not isinstance(worker_provider, str):
        raise RegistryError("Leader and worker providers must be strings")

    primary_pool = _unique_strings(leader.get("primary_pool"), "leader.primary_pool")
    failover_pool = _unique_strings(leader.get("failover_pool"), "leader.failover_pool")
    if not primary_pool or not failover_pool:
        raise RegistryError("Leader pools must be non-empty")
    if set(primary_pool) != set(failover_pool):
        raise RegistryError("Leader primary and failover pools must cover the same accounts")

    roles = workers.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise RegistryError("Worker roles must be a non-empty object")
    assigned: list[str] = []
    for role_name, ids in roles.items():
        if not isinstance(role_name, str) or not role_name.strip():
            raise RegistryError("Worker role names must be non-empty strings")
        role_ids = _unique_strings(ids, f"workers.roles.{role_name}")
        if role_name != "standby" and not role_ids:
            raise RegistryError(f"Required worker role is empty: {role_name}")
        assigned.extend(role_ids)
    if len(assigned) != len(set(assigned)):
        raise RegistryError("A worker connection is assigned to more than one role")

    leader_ids = set(primary_pool)
    worker_ids = set(assigned)
    if leader_ids & worker_ids:
        raise RegistryError(f"Leader/worker connection overlap detected: {sorted(leader_ids & worker_ids)}")

    registry_ids = leader_ids | worker_ids
    actual_ids = set(connections)
    missing_metadata = sorted(registry_ids - actual_ids)
    if missing_metadata:
        raise RegistryError(f"Registry references unknown connections: {missing_metadata}")

    unassigned_active = sorted(
        connection_id
        for connection_id in actual_ids - registry_ids
        if isinstance(connections.get(connection_id), dict) and _status_is_eligible(connections[connection_id])
    )
    if unassigned_active:
        raise RegistryError(f"Eligible connections are not assigned by the authoritative registry: {unassigned_active}")

    for connection_id in sorted(actual_ids):
        _validate_connection_metadata(connection_id, connections[connection_id])
    for connection_id in leader_ids:
        if connections[connection_id]["provider"] != leader_provider:
            raise RegistryError(f"Leader connection {connection_id} has provider {connections[connection_id]['provider']!r}, expected {leader_provider!r}")
    for connection_id in worker_ids:
        if connections[connection_id]["provider"] != worker_provider:
            raise RegistryError(f"Worker connection {connection_id} has provider {connections[connection_id]['provider']!r}, expected {worker_provider!r}")

    # Return an effective in-memory routing view. The on-disk registry remains
    # authoritative configuration; non-eligible lifecycle states are filtered
    # only for consumers that use validate_registry().
    effective = copy.deepcopy(registry)
    effective_leader = effective["architecture"]["leader"]
    effective_workers = effective["architecture"]["workers"]
    effective_leader["primary_pool"] = [
        connection_id for connection_id in primary_pool if _status_is_eligible(connections[connection_id])
    ]
    effective_leader["failover_pool"] = [
        connection_id for connection_id in failover_pool if _status_is_eligible(connections[connection_id])
    ]
    effective_workers["roles"] = {
        role: [connection_id for connection_id in ids if _status_is_eligible(connections[connection_id])]
        for role, ids in roles.items()
    }
    return effective


def get_leader_pool(tier: str = "primary") -> list[str]:
    registry = validate_registry()
    leader = registry["architecture"]["leader"]
    if tier == "primary":
        return list(leader["primary_pool"])
    if tier == "failover":
        return list(leader["failover_pool"])
    raise RegistryError(f"Unknown leader tier: {tier}")


def get_worker_pools() -> dict[str, list[str]]:
    registry = validate_registry()
    roles = registry["architecture"]["workers"]["roles"]
    return {role: list(ids) for role, ids in roles.items()}


def main() -> int:
    registry = validate_registry()
    leader = registry["architecture"]["leader"]
    workers = registry["architecture"]["workers"]
    print("=" * 70)
    print("CONFIGURATION REGISTRY VALIDATION")
    print("=" * 70)
    print(f"Registry         : {REGISTRY_FILE.relative_to(BASE_DIR)}")
    print(f"Leader provider  : {leader['provider']}")
    print(f"Primary accounts : {len(leader['primary_pool'])}")
    print(f"Failover accounts: {len(leader['failover_pool'])}")
    print(f"Worker provider  : {workers['provider']}")
    print(f"Worker roles     : {len(workers['roles'])}")
    print(f"Worker accounts  : {sum(len(ids) for ids in workers['roles'].values())}")
    print("Result           : VALID ✅")
    print("=")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
