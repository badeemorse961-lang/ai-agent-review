from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from model_benchmark import Candidate, GROQ_CANDIDATES, OPENROUTER_CANDIDATES
from protected_secret_store import SecretStore, SecretStoreError


BASE_DIR = Path(__file__).resolve().parent
AUTHORITATIVE_REGISTRY_FILE = BASE_DIR / "config" / "registry.json"
CONNECTION_METADATA_FILE = BASE_DIR / "connections.json"

ELIGIBLE_LIFECYCLES = {"ACTIVE", "VALIDATED"}
INELIGIBLE_LIFECYCLES = {"DISABLED", "FAILED", "INVALID", "REMOVED"}


@dataclass(frozen=True)
class ConnectionInventory:
    connection_id: str
    provider: str
    configured_models: tuple[str, ...]
    capability_roles: tuple[str, ...]
    lifecycle: str
    fingerprint_present: bool
    credential_present: bool
    fingerprint_matches: bool
    assigned: bool
    ready: bool
    eligibility_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "provider": self.provider,
            "configured_models": list(self.configured_models),
            "capability_roles": list(self.capability_roles),
            "lifecycle": self.lifecycle,
            "fingerprint_present": self.fingerprint_present,
            "credential_present": self.credential_present,
            "fingerprint_matches": self.fingerprint_matches,
            "assigned": self.assigned,
            "ready": self.ready,
            "eligible": self.ready,
            "eligibility_reason": self.eligibility_reason,
        }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _natural_id(value: str) -> tuple[int, str]:
    try:
        return int(value.rsplit("-", 1)[1]), value
    except (IndexError, ValueError):
        return 10**9, value


def _assignments(authoritative: Mapping[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    architecture = authoritative.get("architecture", {})
    if not isinstance(architecture, Mapping):
        return result

    leader = architecture.get("leader", {})
    if isinstance(leader, Mapping):
        for connection_id in leader.get("primary_pool", []):
            if isinstance(connection_id, str):
                result[connection_id].append("Leader:Primary")
        for connection_id in leader.get("failover_pool", []):
            if isinstance(connection_id, str):
                result[connection_id].append("Leader:Failover")

    workers = architecture.get("workers", {})
    roles = workers.get("roles", {}) if isinstance(workers, Mapping) else {}
    if isinstance(roles, Mapping):
        for role, connection_ids in roles.items():
            if not isinstance(connection_ids, Sequence) or isinstance(connection_ids, (str, bytes)):
                continue
            for connection_id in connection_ids:
                if isinstance(connection_id, str):
                    result[connection_id].append(f"Worker:{role}")
    return result


def _models_for_connection(
    connection_id: str,
    provider: str,
    authoritative: Mapping[str, Any],
    capability_roles: Sequence[str],
) -> tuple[str, ...]:
    architecture = authoritative.get("architecture", {})
    if not isinstance(architecture, Mapping):
        return ()

    if provider == "openrouter":
        leader = architecture.get("leader", {})
        if not isinstance(leader, Mapping):
            return ()
        models: list[str] = []
        primary_pool = leader.get("primary_pool", [])
        failover_pool = leader.get("failover_pool", [])
        if connection_id in primary_pool:
            model = leader.get("primary_model")
            if isinstance(model, str) and model:
                models.append(model)
        if connection_id in failover_pool:
            model = leader.get("failover_model")
            if isinstance(model, str) and model:
                models.append(model)
        return tuple(dict.fromkeys(models))

    if provider == "groq":
        workers = architecture.get("workers", {})
        model = workers.get("model") if isinstance(workers, Mapping) else None
        return (model,) if isinstance(model, str) and model else ()

    return ()


def _lifecycle(value: Any) -> str:
    text = str(value or "").upper()
    if text == "KEY_ROTATED":
        return "DISABLED"
    return text or "UNKNOWN"


def discover_connection_inventory(
    *,
    authoritative_registry_path: Path = AUTHORITATIVE_REGISTRY_FILE,
    connection_metadata_path: Path = CONNECTION_METADATA_FILE,
    secret_store: SecretStore,
) -> list[ConnectionInventory]:
    authoritative = _load_json(authoritative_registry_path)
    metadata = _load_json(connection_metadata_path)
    connections = metadata.get("connections", {})
    if not isinstance(connections, Mapping):
        raise ValueError("connections.json must contain a connections object")
    assignments = _assignments(authoritative)

    inventory: list[ConnectionInventory] = []
    for connection_id in sorted(connections, key=_natural_id):
        item = connections.get(connection_id)
        if not isinstance(item, Mapping):
            continue
        provider = str(item.get("provider", "")).lower()
        lifecycle = _lifecycle(item.get("status"))
        expected_fp = item.get("key_fingerprint")
        fingerprint_present = isinstance(expected_fp, str) and bool(expected_fp)
        capability_roles = tuple(dict.fromkeys(assignments.get(connection_id, [])))
        configured_models = _models_for_connection(connection_id, provider, authoritative, capability_roles)
        assigned = bool(capability_roles)

        credential_present = False
        fingerprint_matches = False
        if provider and fingerprint_present:
            try:
                credential_present = bool(secret_store.has(connection_id, provider))
            except Exception:
                credential_present = False
            if credential_present:
                try:
                    secret = secret_store.get(connection_id, provider)
                    from connection_manager import fingerprint

                    fingerprint_matches = fingerprint(secret) == expected_fp
                except (SecretStoreError, Exception):
                    fingerprint_matches = False

        if lifecycle in INELIGIBLE_LIFECYCLES:
            ready = False
            reason = f"LIFECYCLE_{lifecycle}"
        elif lifecycle not in ELIGIBLE_LIFECYCLES:
            ready = False
            reason = "LIFECYCLE_NOT_ELIGIBLE"
        elif not assigned:
            ready = False
            reason = "NOT_ASSIGNED_BY_REGISTRY"
        elif not configured_models:
            ready = False
            reason = "MODEL_CONFIGURATION_MISSING"
        elif not fingerprint_present:
            ready = False
            reason = "FINGERPRINT_MISSING"
        elif not credential_present:
            ready = False
            reason = "SECRET_RECORD_MISSING"
        elif not fingerprint_matches:
            ready = False
            reason = "FINGERPRINT_MISMATCH"
        else:
            ready = True
            reason = "READY_LOCAL_CREDENTIAL_AND_REGISTRY_STATE"

        inventory.append(
            ConnectionInventory(
                connection_id=connection_id,
                provider=provider,
                configured_models=configured_models,
                capability_roles=capability_roles,
                lifecycle=lifecycle,
                fingerprint_present=fingerprint_present,
                credential_present=credential_present,
                fingerprint_matches=fingerprint_matches,
                assigned=assigned,
                ready=ready,
                eligibility_reason=reason,
            )
        )
    return inventory


def build_phase_a_candidates(
    inventory: Sequence[ConnectionInventory],
    *,
    providers: Sequence[str] = ("openrouter", "groq"),
) -> list[Candidate]:
    """Create execution candidates from eligible connections and the existing model shortlist.

    Model capability is deliberately independent from connection identity. Each eligible
    connection is an execution/account instance for every shortlisted model of its provider.
    The benchmark's model IDs and scoring logic remain unchanged.
    """
    candidates: list[Candidate] = []
    allowed = {provider.lower() for provider in providers}
    model_sets = {
        "openrouter": OPENROUTER_CANDIDATES,
        "groq": GROQ_CANDIDATES,
    }
    for item in inventory:
        if not item.ready or item.provider not in allowed:
            continue
        for model in model_sets.get(item.provider, ()):
            candidates.append(Candidate(item.provider, model, item.connection_id))
    return candidates


def inventory_summary(inventory: Sequence[ConnectionInventory]) -> dict[str, Any]:
    eligible = [item for item in inventory if item.ready]
    models: dict[str, set[str]] = defaultdict(set)
    for item in eligible:
        for model in item.configured_models:
            models[f"{item.provider}:{model}"].add(item.connection_id)
    return {
        "total_connections": len(inventory),
        "eligible_connections": len(eligible),
        "excluded_connections": len(inventory) - len(eligible),
        "eligible_by_provider": {
            provider: sum(1 for item in eligible if item.provider == provider)
            for provider in ("openrouter", "groq")
        },
        "configured_model_connection_counts": {
            key: len(value) for key, value in sorted(models.items())
        },
        "connections": [item.to_dict() for item in inventory],
    }
