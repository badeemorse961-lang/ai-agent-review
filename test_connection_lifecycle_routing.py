from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from config_registry import validate_registry


def write_fixture(tmp_path: Path, status: str) -> tuple[Path, Path]:
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
                "key_fingerprint": hashlib.sha256(b"OR-01").hexdigest(),
                "status": "VALIDATED",
                "active": False,
            },
            **{
                f"GROQ-{i:02d}": {
                    "connection_id": f"GROQ-{i:02d}",
                    "provider": "groq",
                    "key_fingerprint": hashlib.sha256(f"GROQ-{i:02d}".encode()).hexdigest(),
                    "status": status if i == 1 else "VALIDATED",
                    "active": status == "ACTIVE" if i == 1 else False,
                }
                for i in range(1, 7)
            },
        },
    }
    config_path = tmp_path / "registry.json"
    connections_path = tmp_path / "connections.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    connections_path.write_text(json.dumps(connections), encoding="utf-8")
    return config_path, connections_path


def test_disabled_connection_is_filtered_from_effective_worker_pool(tmp_path: Path) -> None:
    config_path, connections_path = write_fixture(tmp_path, "DISABLED")
    with patch("config_registry.REGISTRY_FILE", config_path), patch("config_registry.CONNECTIONS_FILE", connections_path):
        registry = validate_registry()
    assert "GROQ-01" not in registry["architecture"]["workers"]["roles"]["coder"]
    assert "GROQ-02" in registry["architecture"]["workers"]["roles"]["debugger"]


def test_validated_legacy_metadata_remains_routable(tmp_path: Path) -> None:
    config_path, connections_path = write_fixture(tmp_path, "VALIDATED")
    with patch("config_registry.REGISTRY_FILE", config_path), patch("config_registry.CONNECTIONS_FILE", connections_path):
        registry = validate_registry()
    assert "GROQ-01" in registry["architecture"]["workers"]["roles"]["coder"]
