from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from leader_router import LeaderRouter, LeaderUnavailable
from worker_router import WorkerRouter


def write_registry_fixture(tmp_path: Path, *, groq_status: str = "ACTIVE") -> tuple[Path, Path, Path, Path]:
    config = {
        "architecture": {
            "leader": {
                "provider": "openrouter",
                "primary_model": "m1",
                "failover_model": "m2",
                "primary_pool": ["OR-01"],
                "failover_pool": ["OR-01"],
            },
            "workers": {
                "provider": "groq",
                "model": "g1",
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
                "connection_id": "OR-01",
                "provider": "openrouter",
                "key_fingerprint": hashlib.sha256(b"or-secret").hexdigest(),
                "role": None,
                "status": "ACTIVE",
                "active": True,
            },
            **{
                f"GROQ-{i:02d}": {
                    "connection_id": f"GROQ-{i:02d}",
                    "provider": "groq",
                    "key_fingerprint": hashlib.sha256(f"groq-{i}".encode()).hexdigest(),
                    "role": None,
                    "status": groq_status if i == 1 else "ACTIVE",
                    "active": True,
                }
                for i in range(1, 7)
            },
        },
    }
    registry_path = tmp_path / "registry.json"
    connections_path = tmp_path / "connections.json"
    leader_health = tmp_path / "leader_health.json"
    worker_health = tmp_path / "worker_health.json"
    leader_state = tmp_path / "leader_state.json"
    worker_state = tmp_path / "worker_state.json"

    registry_path.write_text(json.dumps(config), encoding="utf-8")
    connections_path.write_text(json.dumps(connections), encoding="utf-8")
    leader_health.write_text(
        json.dumps({
            "provider": "openrouter",
            "models": {
                "m1": {"provider": "openrouter", "healthy": ["OR-01"], "failed": []},
                "m2": {"provider": "openrouter", "healthy": ["OR-01"], "failed": []},
            },
        }),
        encoding="utf-8",
    )
    worker_health.write_text(
        json.dumps({"provider": "groq", "healthy": [f"GROQ-{i:02d}" for i in range(1, 7)], "failed": []}),
        encoding="utf-8",
    )
    return registry_path, connections_path, leader_health, worker_health, leader_state, worker_state


def test_leader_router_excludes_disabled_connection(tmp_path: Path) -> None:
    registry, connections, leader_health, _, leader_state, _ = write_registry_fixture(tmp_path, groq_status="ACTIVE")
    connections_data = json.loads(connections.read_text(encoding="utf-8"))
    connections_data["connections"]["OR-01"]["status"] = "DISABLED"
    connections_data["connections"]["OR-01"]["active"] = False
    connections.write_text(json.dumps(connections_data), encoding="utf-8")

    with patch("config_registry.REGISTRY_FILE", registry), patch("config_registry.CONNECTIONS_FILE", connections), patch("leader_router.REGISTRY_FILE", registry):
        router = LeaderRouter(health_file=leader_health, state_file=leader_state)
        assert router.active_pool("ULTRA") == []
        with pytest.raises(LeaderUnavailable):
            router.acquire("TASK-DISABLED")


def test_worker_router_excludes_failed_connection_from_role(tmp_path: Path) -> None:
    registry, connections, _, worker_health, _, worker_state = write_registry_fixture(tmp_path, groq_status="FAILED")

    with patch("config_registry.REGISTRY_FILE", registry), patch("config_registry.CONNECTIONS_FILE", connections), patch("worker_router.REGISTRY_FILE", registry):
        router = WorkerRouter(health_file=worker_health, state_file=worker_state)
        assert "GROQ-01" not in router.available_workers("coder")


def test_removed_connection_is_not_routable(tmp_path: Path) -> None:
    registry, connections, _, worker_health, _, worker_state = write_registry_fixture(tmp_path, groq_status="REMOVED")

    with patch("config_registry.REGISTRY_FILE", registry), patch("config_registry.CONNECTIONS_FILE", connections), patch("worker_router.REGISTRY_FILE", registry):
        router = WorkerRouter(health_file=worker_health, state_file=worker_state)
        assert "GROQ-01" not in router.available_workers("coder")
