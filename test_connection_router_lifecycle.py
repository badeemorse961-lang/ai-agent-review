from __future__ import annotations

import hashlib
import json
from pathlib import Path

from leader_router import LeaderRouter
from worker_router import WorkerRouter


def write_registry_fixture(tmp_path: Path, *, groq_status: str = "ACTIVE", groq_active: bool = True) -> tuple[Path, Path, Path, Path, Path, Path]:
    config = {
        "architecture": {
            "leader": {
                "provider": "openrouter",
                "primary_model": "m1",
                "failover_model": "m2",
                "primary_pool": ["OR-01", "OR-02"],
                "failover_pool": ["OR-01", "OR-02"],
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
            "OR-01": {"connection_id": "OR-01", "provider": "openrouter", "key_fingerprint": hashlib.sha256(b"or-secret-1").hexdigest(), "role": None, "status": "ACTIVE", "active": True, "credential_validated": True, "validation_required": False},
            "OR-02": {"connection_id": "OR-02", "provider": "openrouter", "key_fingerprint": hashlib.sha256(b"or-secret-2").hexdigest(), "role": None, "status": "ACTIVE", "active": True, "credential_validated": True, "validation_required": False},
            **{
                f"GROQ-{i:02d}": {
                    "connection_id": f"GROQ-{i:02d}",
                    "provider": "groq",
                    "key_fingerprint": hashlib.sha256(f"groq-{i}".encode()).hexdigest(),
                    "role": None,
                    "status": groq_status if i == 1 else "ACTIVE",
                    "active": groq_active if i == 1 else True,
                    "credential_validated": groq_status not in {"FAILED", "INVALID", "REMOVED"},
                    "validation_required": groq_status in {"FAILED", "INVALID"},
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

    leader_healthy = ["OR-01", "OR-02"]
    leader_failed: list[str] = []
    leader_health.write_text(
        json.dumps({
            "provider": "openrouter",
            "models": {
                "m1": {"provider": "openrouter", "healthy": leader_healthy, "failed": leader_failed},
                "m2": {"provider": "openrouter", "healthy": leader_healthy, "failed": leader_failed},
            },
        }),
        encoding="utf-8",
    )

    worker_healthy = [f"GROQ-{i:02d}" for i in range(1, 7)]
    worker_failed: list[str] = []
    if groq_status != "ACTIVE" or not groq_active:
        worker_healthy.remove("GROQ-01")
        worker_failed.append("GROQ-01")
    worker_health.write_text(
        json.dumps({"provider": "groq", "healthy": worker_healthy, "failed": worker_failed}),
        encoding="utf-8",
    )
    return registry_path, connections_path, leader_health, worker_health, leader_state, worker_state


def test_leader_router_excludes_disabled_connection(tmp_path: Path) -> None:
    registry, connections, leader_health, _, leader_state, _ = write_registry_fixture(tmp_path)
    data = json.loads(connections.read_text(encoding="utf-8"))
    data["connections"]["OR-01"]["status"] = "DISABLED"
    data["connections"]["OR-01"]["active"] = False
    connections.write_text(json.dumps(data), encoding="utf-8")
    health = json.loads(leader_health.read_text(encoding="utf-8"))
    for model in ("m1", "m2"):
        health["models"][model]["healthy"].remove("OR-01")
        health["models"][model]["failed"].append("OR-01")
    leader_health.write_text(json.dumps(health), encoding="utf-8")
    router = LeaderRouter(health_file=leader_health, state_file=leader_state, registry_file=registry)
    assert router.active_pool("ULTRA") == ["OR-02"]
    lease = router.acquire("TASK-DISABLED")
    assert lease.account_id == "OR-02"


def test_worker_router_excludes_failed_invalid_and_removed_connections(tmp_path: Path) -> None:
    for lifecycle in ("FAILED", "INVALID", "REMOVED"):
        case = tmp_path / lifecycle.lower()
        case.mkdir()
        registry, _, _, worker_health, _, worker_state = write_registry_fixture(case, groq_status=lifecycle, groq_active=False)
        router = WorkerRouter(health_file=worker_health, state_file=worker_state, registry_file=registry)
        assert "GROQ-01" not in router.available_workers("coder")


def test_active_connection_remains_routable(tmp_path: Path) -> None:
    registry, _, _, worker_health, _, worker_state = write_registry_fixture(tmp_path, groq_status="ACTIVE", groq_active=True)
    router = WorkerRouter(health_file=worker_health, state_file=worker_state, registry_file=registry)
    assert "GROQ-01" in router.available_workers("coder")
