from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from application_boundary import ApplicationIntent
from connection_control_center import ConnectionControlCenterService
from connection_manager import fingerprint, replace_connection_credential, validate_connection
from leader_router import LeaderRouter, LeaderUnavailable
from protected_secret_store import MemorySecretStore


def write_fixture(tmp_path: Path, *, status: str = "ACTIVE") -> tuple[Path, Path, Path, Path]:
    registry = tmp_path / "registry.json"
    metadata = tmp_path / "connections.json"
    health = tmp_path / "leader_health.json"
    state = tmp_path / "leader_state.json"
    config = {
        "architecture": {
            "leader": {
                "provider": "openrouter",
                "primary_model": "model-a",
                "failover_model": "model-b",
                "primary_pool": ["OR-01"],
                "failover_pool": ["OR-01"],
            },
            "workers": {
                "provider": "groq",
                "model": "worker-model",
                "roles": {
                    "coder": ["GROQ-01"],
                    "debugger": ["GROQ-02"],
                    "tester": ["GROQ-03"],
                    "architect": ["GROQ-04"],
                    "reviewer": ["GROQ-05"],
                    "standby": ["GROQ-06"],
                },
            },
        }
    }
    connections = {
        "version": 2,
        "role_source": "config/registry.json",
        "connections": {
            "OR-01": {
                "connection_id": "OR-01", "provider": "openrouter",
                "key_fingerprint": fingerprint("old-leader-key"), "role": None,
                "status": status, "active": status == "ACTIVE",
                "credential_validated": status == "ACTIVE", "validation_required": status != "ACTIVE",
            },
            **{
                f"GROQ-{i:02d}": {
                    "connection_id": f"GROQ-{i:02d}", "provider": "groq",
                    "key_fingerprint": hashlib.sha256(f"g-{i}".encode()).hexdigest(), "role": None,
                    "status": "ACTIVE", "active": True,
                    "credential_validated": True, "validation_required": False,
                } for i in range(1, 7)
            },
        },
    }
    registry.write_text(json.dumps(config), encoding="utf-8")
    metadata.write_text(json.dumps(connections), encoding="utf-8")
    health.write_text(json.dumps({"provider": "openrouter", "models": {
        "model-a": {"provider": "openrouter", "healthy": ["OR-01"], "failed": []},
        "model-b": {"provider": "openrouter", "healthy": ["OR-01"], "failed": []},
    }}), encoding="utf-8")
    return registry, metadata, health, state


def test_all_existing_leader_credentials_failed_then_stable_id_rotation_recovers_router(tmp_path: Path) -> None:
    registry, metadata, health, state = write_fixture(tmp_path, status="FAILED")
    store = MemorySecretStore()
    store.put("OR-01", "openrouter", "old-leader-key", fingerprint("old-leader-key"))
    replacement = tmp_path / "replacement.txt"
    replacement.write_text("OR-01=new-leader-key\n", encoding="utf-8")

    with patch("config_registry.REGISTRY_FILE", registry), patch("config_registry.CONNECTIONS_FILE", metadata), patch("leader_router.REGISTRY_FILE", registry):
        router = LeaderRouter(health_file=health, state_file=state, registry_file=registry)
        assert router.active_pool("ULTRA") == []
        with pytest.raises(LeaderUnavailable):
            router.acquire("TASK-LEADER-DOWN")

        before = json.loads(metadata.read_text(encoding="utf-8"))["connections"]["OR-01"]["key_fingerprint"]
        local = json.loads(metadata.read_text(encoding="utf-8"))
        with patch("connection_manager.REGISTRY_FILE", metadata), patch("connection_manager.AUTHORITATIVE_REGISTRY_FILE", registry):
            replace_connection_credential("OR-01", replacement, local, secret_store=store, persist=True)
            after = local["connections"]["OR-01"]
            assert after["connection_id"] == "OR-01"
            assert after["key_fingerprint"] != before
            assert after["status"] == "DISABLED"
            assert after["validation_required"] is True

            validate_connection("OR-01", registry=local, secret_store=store, validator=lambda *_: None, persist=True)
            recovered = json.loads(metadata.read_text(encoding="utf-8"))["connections"]["OR-01"]
            assert recovered["connection_id"] == "OR-01"
            assert recovered["status"] == "ACTIVE"
            assert recovered["active"] is True
            assert recovered["credential_validated"] is True
            assert recovered["validation_required"] is False

        recovered_router = LeaderRouter(health_file=health, state_file=state, registry_file=registry)
        assert recovered_router.active_pool("ULTRA") == ["OR-01"]
        lease = recovered_router.acquire("TASK-RECOVERED")
        assert lease.account_id == "OR-01"
        assert lease.tier == "ULTRA"


def test_control_center_injects_one_shared_store_into_provider_transport() -> None:
    store = MemorySecretStore()
    service = ConnectionControlCenterService(secret_store=store, autowire_core=False)
    assert getattr(service, "secret_store") is store
    transport = getattr(service, "leader_transport")
    assert getattr(transport, "secret_store") is store


def test_new_unassigned_key_is_stored_but_not_auto_assigned(tmp_path: Path) -> None:
    registry, metadata, _, _ = write_fixture(tmp_path, status="ACTIVE")
    store = MemorySecretStore()
    source = tmp_path / "new.txt"
    source.write_text("brand-new-key\n", encoding="utf-8")
    local = json.loads(metadata.read_text(encoding="utf-8"))
    with patch("connection_manager.REGISTRY_FILE", metadata):
        from connection_manager import import_provider
        summary = import_provider("openrouter", source, local, "OR", secret_store=store, persist=True)
    assert summary.imported_count == 1
    new_id = summary.connection_ids[0]
    assert new_id != "OR-01"
    item = local["connections"][new_id]
    assert item["status"] == "DISABLED"
    assert item["active"] is False
    assert store.has(new_id)
    authoritative_before = json.loads(registry.read_text(encoding="utf-8"))
    assert new_id not in authoritative_before["architecture"]["leader"]["primary_pool"]
    assert new_id not in authoritative_before["architecture"]["leader"]["failover_pool"]
