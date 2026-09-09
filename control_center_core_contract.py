from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from config_registry import load_registry as load_authoritative_registry
from connection_manager import (
    PENDING_ASSIGNMENT,
    credential_record_present,
    get_external_secret_sync_state,
    load_registry as load_connection_metadata,
    replace_connection_credential,
    sync_external_secret_sources,
)
from protected_secret_store import WindowsProtectedSecretStore


def _assignments(registry: Mapping[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    architecture = registry.get("architecture", {})
    if not isinstance(architecture, Mapping):
        return result
    leader = architecture.get("leader", {})
    if isinstance(leader, Mapping):
        for pool_name in ("primary_pool", "failover_pool"):
            ids = leader.get(pool_name, [])
            if isinstance(ids, list):
                for connection_id in ids:
                    result.setdefault(str(connection_id), []).append(f"leader.{pool_name}")
    workers = architecture.get("workers", {})
    roles = workers.get("roles", {}) if isinstance(workers, Mapping) else {}
    if isinstance(roles, Mapping):
        for role, ids in roles.items():
            if isinstance(ids, list):
                for connection_id in ids:
                    result.setdefault(str(connection_id), []).append(f"worker.{role}")
    return result


def _model(registry: Mapping[str, Any], connection_id: str) -> str | None:
    architecture = registry.get("architecture", {})
    if not isinstance(architecture, Mapping):
        return None
    leader = architecture.get("leader", {})
    if isinstance(leader, Mapping):
        primary_ids = set(leader.get("primary_pool", []) or [])
        failover_ids = set(leader.get("failover_pool", []) or [])
        models: list[str] = []
        if connection_id in primary_ids and isinstance(leader.get("primary_model"), str):
            models.append(str(leader["primary_model"]))
        if connection_id in failover_ids and isinstance(leader.get("failover_model"), str):
            models.append(str(leader["failover_model"]))
        if models:
            return " / ".join(dict.fromkeys(models))
    workers = architecture.get("workers", {})
    if isinstance(workers, Mapping):
        value = workers.get("model")
        return value if isinstance(value, str) else None
    return None


def _fingerprint_display(value: Any) -> str:
    if not isinstance(value, str) or len(value) < 8:
        return "absent"
    return f"{value[:8]}…{value[-4:]}"


def connection_read_model(runtime_status_by_id: Mapping[str, str] | None = None) -> dict[str, Any]:
    authoritative = load_authoritative_registry()
    metadata = load_connection_metadata()
    assignments = _assignments(authoritative)
    connections = metadata.get("connections", {})
    runtime = runtime_status_by_id or {}
    views: list[dict[str, Any]] = []
    for connection_id, item in sorted(connections.items()):
        if not isinstance(item, Mapping):
            continue
        provider = str(item.get("provider", "unknown"))
        status = str(item.get("status", "UNKNOWN"))
        assigned = tuple(sorted(assignments.get(connection_id, [])))
        pending = status == PENDING_ASSIGNMENT
        credential_present = credential_record_present(connection_id)
        fingerprint_present = isinstance(item.get("key_fingerprint"), str) and bool(item.get("key_fingerprint"))
        active = bool(item.get("active"))
        routable = (not pending) and active and bool(assigned)
        runtime_status = str(runtime.get(connection_id, "UNOBSERVED"))
        if pending:
            ready_state = PENDING_ASSIGNMENT
            ready_reason = "Awaiting explicit assignment in config/registry.json; inactive and non-routable"
        elif status == "REMOVED":
            ready_state = "REMOVED"
            ready_reason = "Connection has been removed"
        elif status in {"FAILED", "INVALID"} or runtime_status == "FAILED":
            ready_state = "FAILED"
            ready_reason = str(item.get("failure_reason", "Connection failed validation/runtime checks"))
        elif not assigned:
            ready_state = "STORED"
            ready_reason = "Stored metadata is not assigned by the authoritative registry"
        elif not fingerprint_present or not credential_present:
            ready_state = "SETUP"
            ready_reason = "Protected credential and fingerprint must both be present"
        elif not active:
            ready_state = "STORED"
            ready_reason = "Credential is securely stored but the connection is disabled"
        elif runtime_status not in {"HEALTHY", "LEASED", "UNOBSERVED"}:
            ready_state = "SETUP"
            ready_reason = "Runtime health is not in an eligible state"
        else:
            ready_state = "READY"
            ready_reason = "Securely stored, assigned, and lifecycle-eligible for routing"
        views.append({
            "connection_id": connection_id,
            "provider": provider,
            "model": _model(authoritative, connection_id),
            "assignments": list(assigned),
            "configured": bool(assigned),
            "metadata_status": status,
            "active": active,
            "routable": routable,
            "runtime_status": runtime_status,
            "fingerprint_present": fingerprint_present,
            "fingerprint_display": _fingerprint_display(item.get("key_fingerprint")),
            "credential_present": credential_present,
            "ready_state": ready_state,
            "ready_reason": ready_reason,
            "non_routable_reason": ready_reason if not routable else "",
        })
    return {"connections": views, "external_secret_sources": get_external_secret_sync_state(), "raw_secrets_returned": False}


def connection_runtime_status_by_id(routers: tuple[Any, ...]) -> dict[str, str]:
    status: dict[str, str] = {}
    for router in routers:
        if router is None:
            continue
        snapshot = router.snapshot()
        if not isinstance(snapshot, Mapping):
            continue
        failed = set(snapshot.get("runtime_failed", [])) | set(snapshot.get("failed", []))
        healthy = set(snapshot.get("healthy", []))
        leases = snapshot.get("leases", {})
        leased: set[str] = set()
        if isinstance(leases, Mapping):
            for lease in leases.values():
                if isinstance(lease, Mapping):
                    worker_id = lease.get("worker_id", lease.get("account_id"))
                    if isinstance(worker_id, str):
                        leased.add(worker_id)
        for connection_id in failed:
            status[str(connection_id)] = "FAILED"
        for connection_id in healthy:
            if str(connection_id) not in status:
                status[str(connection_id)] = "HEALTHY"
        for connection_id in leased:
            if str(connection_id) not in status:
                status[str(connection_id)] = "LEASED"
    return status


def sync_and_get_read_model(runtime_status_by_id: Mapping[str, str] | None = None) -> dict[str, Any]:
    sync_external_secret_sources()
    return connection_read_model(runtime_status_by_id)


def replace_connection_credential_from_ui(connection_id: str, source_path: str) -> Mapping[str, Any]:
    """Core-owned credential replacement gateway; UI supplies only identity + source path."""
    registry = load_connection_metadata()
    summary = replace_connection_credential(
        connection_id,
        Path(source_path).resolve(),
        registry,
        secret_store=WindowsProtectedSecretStore(),
    )
    return summary.to_dict()
