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
    with patch("connection_control_center.load_registry", return_value=registry):
        with patch("connection_manager.save_registry"):
            result = service.dispatch(
                ApplicationIntent(
                    "import_provider_connections",
                    {"provider": "groq", "source_path": str(source)},
                )
            )

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
    with patch("connection_control_center.load_registry", return_value=registry):
        with patch("connection_manager.save_registry"):
            result = service.dispatch(
                ApplicationIntent("import_provider_connections", {"provider": "groq", "source_path": str(source)})
            )

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


def test_readiness_marker_requires_credential_assignment_and_eligible_status() -> None:
    store = MemorySecretStore()
    secret = "ready-secret"
    store.put("GROQ-01", "groq", secret, fingerprint(secret))
    service = ConnectionControlCenterService(secret_store=store, autowire_core=False)
    app = object.__new__(ConnectionControlCenterApp)
    app.service = service

    base = {
        "connection_id": "GROQ-01",
        "provider": "groq",
        "metadata_status": "ACTIVE",
        "runtime_status": "UNOBSERVED",
        "assignments": ["coder"],
        "fingerprint_present": True,
    }
    readiness, reason = app._connection_readiness(base)
    assert readiness == "READY"
    assert reason == "Ready · automatic use"

    stored = dict(base, assignments=[])
    readiness, _ = app._connection_readiness(stored)
    assert readiness == "STORED"

    disabled = dict(base, metadata_status="DISABLED")
    readiness, _ = app._connection_readiness(disabled)
    assert readiness == "STORED"

    failed = dict(base, runtime_status="FAILED")
    readiness, _ = app._connection_readiness(failed)
    assert readiness == "FAILED"

    missing_credential = dict(base, connection_id="GROQ-02")
    readiness, _ = app._connection_readiness(missing_credential)
    assert readiness == "SETUP"


def test_enable_reports_registry_assignment_block_without_ui_bypass() -> None:
    registry = make_registry()
    store = MemorySecretStore()
    secret = "old-secret"
    store.put("GROQ-01", "groq", secret, fingerprint(secret))
    service = ConnectionControlCenterService(secret_store=store, autowire_core=False)

    with patch("connection_control_center.load_registry", return_value=registry), \
         patch("connection_control_center.enable_connection", side_effect=ValueError("Connection must be assigned in config/registry.json before it can be enabled")):
        result = service.dispatch(ApplicationIntent("enable_connection", {"connection_id": "GROQ-01"}))

    assert result.status == "BLOCKED"
    assert result.data["setup_required"] == "REGISTRY_ASSIGNMENT"
    assert "config/registry.json" in (result.error or "")
