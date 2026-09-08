from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from application_boundary import ApplicationIntent
from connection_control_center import ConnectionControlCenterApp, ConnectionControlCenterService
from connection_manager import fingerprint
from protected_secret_store import MemorySecretStore


def make_registry() -> dict:
    return {
        "version": 2,
        "role_source": "config/registry.json",
        "connections": {
            "GROQ-01": {
                "connection_id": "GROQ-01",
                "provider": "groq",
                "key_fingerprint": fingerprint("old-secret"),
                "role": None,
                "status": "ACTIVE",
                "active": True,
                "credential_validated": True,
                "validation_required": False,
            }
        },
    }


def test_import_result_is_redacted_and_persistent(tmp_path: Path) -> None:
    registry = make_registry()
    store = MemorySecretStore()
    store.put("GROQ-01", "groq", "old-secret", fingerprint("old-secret"))
    source = tmp_path / "new.txt"
    source.write_text("old-secret\nnew-secret\n", encoding="utf-8")
    service = ConnectionControlCenterService(secret_store=store, autowire_core=False)
    with patch("connection_control_center.load_registry", return_value=registry), patch("connection_manager.save_registry"):
        result = service.dispatch(ApplicationIntent("import_provider_connections", {"provider": "groq", "source_path": str(source)}))
    assert result.status == "OK"
    assert result.data["imported_count"] == 1
    assert result.data["already_present_count"] == 1
    assert result.data["raw_secrets_returned"] is False
    assert "new-secret" not in repr(result.data)
    assert store.has("GROQ-01") and store.has("GROQ-02")


def test_no_changes_is_truthful(tmp_path: Path) -> None:
    registry = make_registry()
    store = MemorySecretStore()
    secret = "old-secret"
    store.put("GROQ-01", "groq", secret, fingerprint(secret))
    source = tmp_path / "same.txt"
    source.write_text(f"{secret}\n", encoding="utf-8")
    service = ConnectionControlCenterService(secret_store=store, autowire_core=False)
    with patch("connection_control_center.load_registry", return_value=registry), patch("connection_manager.save_registry"):
        result = service.dispatch(ApplicationIntent("import_provider_connections", {"provider": "groq", "source_path": str(source)}))
    assert result.status == "NO_CHANGES"
    assert result.data["already_present_count"] == 1


def test_disable_enable_and_remove_are_explicit() -> None:
    registry = make_registry()
    store = MemorySecretStore()
    secret = "old-secret"
    store.put("GROQ-01", "groq", secret, fingerprint(secret))
    service = ConnectionControlCenterService(secret_store=store, autowire_core=False)
    with patch("connection_control_center.load_registry", return_value=registry), \
         patch("connection_control_center.disable_connection") as disable, \
         patch("connection_control_center.enable_connection") as enable, \
         patch("connection_control_center.remove_connection") as remove:
        result = service.dispatch(ApplicationIntent("disable_connection", {"connection_id": "GROQ-01"}))
        assert result.status == "OK"
        disable.assert_called_once()
        result = service.dispatch(ApplicationIntent("enable_connection", {"connection_id": "GROQ-01"}))
        assert result.status == "OK"
        enable.assert_called_once()
        result = service.dispatch(ApplicationIntent("remove_connection", {"connection_id": "GROQ-01", "confirmed": False}))
        assert result.status == "REJECTED"
        result = service.dispatch(ApplicationIntent("remove_connection", {"connection_id": "GROQ-01", "confirmed": True}))
        assert result.status == "OK"
        remove.assert_called_once()


def test_readiness_helper_requires_credential_assignment_and_validation() -> None:
    from application_boundary import ControlCenterService
    assert ControlCenterService._connection_ready_state(
        metadata_status="ACTIVE", configured=True, assignments=("coder",), runtime_status="UNOBSERVED",
        fingerprint_present=True, credential_present=True,
    ) == ("READY", "Securely stored, assigned, and lifecycle-eligible for routing")
    assert ControlCenterService._connection_ready_state(
        metadata_status="ACTIVE", configured=False, assignments=(), runtime_status="UNOBSERVED",
        fingerprint_present=True, credential_present=True,
    )[0] == "STORED"
    assert ControlCenterService._connection_ready_state(
        metadata_status="DISABLED", configured=True, assignments=("coder",), runtime_status="HEALTHY",
        fingerprint_present=True, credential_present=True,
    )[0] == "STORED"
    assert ControlCenterService._connection_ready_state(
        metadata_status="FAILED", configured=True, assignments=("coder",), runtime_status="FAILED",
        fingerprint_present=True, credential_present=True,
    )[0] == "FAILED"
    assert ControlCenterService._connection_ready_state(
        metadata_status="ACTIVE", configured=True, assignments=("coder",), runtime_status="UNOBSERVED",
        fingerprint_present=True, credential_present=False,
    )[0] == "SETUP"
    assert ControlCenterService._connection_ready_state(
        metadata_status="ACTIVE", configured=True, assignments=("coder",), runtime_status="UNOBSERVED",
        fingerprint_present=True, credential_present=True,
    )[0] == "READY"


def test_service_readiness_state_is_truthful_and_no_secret_is_exposed() -> None:
    store = MemorySecretStore()
    secret = "service-ready-secret"
    store.put("GROQ-01", "groq", secret, fingerprint(secret))
    service = ConnectionControlCenterService(secret_store=store, autowire_core=False)
    authoritative = {"architecture": {"leader": {"primary_pool": [], "failover_pool": []}, "workers": {"roles": {"coder": ["GROQ-01"]}}}}
    metadata = {"role_source": "config/registry.json", "connections": {"GROQ-01": {"connection_id": "GROQ-01", "provider": "groq", "key_fingerprint": fingerprint(secret), "status": "ACTIVE", "active": True, "credential_validated": True, "validation_required": False}}}
    with patch("application_boundary.load_authoritative_registry", return_value=authoritative), patch("application_boundary.load_connections", return_value=metadata):
        service.worker_router = None
        result = service.dispatch(ApplicationIntent("refresh_connections", {}))
    item = result.data["connections"][0]
    assert item["ready_state"] == "READY"
    assert item["credential_present"] is True
    assert item["configured"] is True
    assert secret not in repr(item)


def test_enable_reports_validation_or_registry_block_without_ui_bypass() -> None:
    registry = make_registry()
    store = MemorySecretStore()
    store.put("GROQ-01", "groq", "old-secret", fingerprint("old-secret"))
    service = ConnectionControlCenterService(secret_store=store, autowire_core=False)
    with patch("connection_control_center.load_registry", return_value=registry), patch("connection_control_center.enable_connection", side_effect=ValueError("Successful credential validation is required before activation")):
        result = service.dispatch(ApplicationIntent("enable_connection", {"connection_id": "GROQ-01"}))
    assert result.status == "BLOCKED"
    assert result.data["setup_required"] == "VALIDATION_OR_REGISTRY_ASSIGNMENT"
    assert "validation" in (result.error or "").lower()
