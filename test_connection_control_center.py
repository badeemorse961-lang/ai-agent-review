from __future__ import annotations

from pathlib import Path

from application_boundary import ApplicationIntent
from connection_control_center import ConnectionControlCenterService
from connection_manager import PENDING_ASSIGNMENT, enable_connection, fingerprint


def test_connection_actions_remain_typed_core_intents(monkeypatch, tmp_path: Path) -> None:
    metadata = {"version": 2, "role_source": "config/registry.json", "connections": {"GROQ-99": {"connection_id": "GROQ-99", "provider": "groq", "key_fingerprint": fingerprint("synthetic"), "status": "PENDING_ASSIGNMENT", "active": False, "role": None}}}
    metadata_path = tmp_path / "connections.json"
    import json
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr("connection_manager.REGISTRY_FILE", metadata_path)
    service = ConnectionControlCenterService(autowire_core=False)
    result = service.dispatch(ApplicationIntent("enable_connection", {"connection_id": "GROQ-99"}))
    assert result.status == "BLOCKED"
    assert result.data["status"] == PENDING_ASSIGNMENT
    assert result.data["active"] is False


def test_connection_service_does_not_accept_legacy_import_intent() -> None:
    service = ConnectionControlCenterService(autowire_core=False)
    result = service.dispatch(ApplicationIntent("import_provider_connections", {}))
    assert result.status == "REJECTED"


def test_replace_is_an_explicit_typed_intent() -> None:
    service = ConnectionControlCenterService(autowire_core=False)
    result = service.dispatch(ApplicationIntent("replace_connection_credential", {}))
    assert result.status == "REJECTED"
