from __future__ import annotations

import json
from pathlib import Path

import connection_manager
from application_boundary import ApplicationIntent, ControlCenterService
from control_center_core_contract import connection_read_model

FORBIDDEN_UI_SYMBOLS = ("read_secret_source", "import_provider(", "import_known_provider_credentials", "fingerprint(", "SecretStore", "WindowsProtectedSecretStore")


def _configure(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    metadata = tmp_path / "connections.json"
    metadata.write_text(json.dumps({"version": 2, "role_source": "config/registry.json", "connections": {}}), encoding="utf-8")
    monkeypatch.setattr(connection_manager, "REGISTRY_FILE", metadata)
    authoritative = tmp_path / "registry.json"
    authoritative.write_text(json.dumps({"architecture": {"leader": {"primary_pool": [], "failover_pool": []}, "workers": {"roles": {}}}}), encoding="utf-8")
    monkeypatch.setattr(connection_manager, "AUTHORITATIVE_REGISTRY_FILE", authoritative)
    source_dir = tmp_path / "sources"; source_dir.mkdir()
    monkeypatch.setenv("AI_AGENT_SECRET_DIR", str(source_dir)); monkeypatch.delenv("AI_AGENT_ALLOW_LEGACY_SECRET_PATH", raising=False)
    return metadata, source_dir


def _read(metadata: Path) -> dict: return json.loads(metadata.read_text(encoding="utf-8"))


def test_A_missing_sources(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path); result = connection_manager.sync_external_secret_sources()
    assert result["groq"]["source_exists"] is False and result["openrouter"]["source_exists"] is False
    assert connection_manager.get_external_secret_sync_state()["last_sync_at"]


def test_B_initial_import(monkeypatch, tmp_path: Path) -> None:
    metadata, source_dir = _configure(monkeypatch, tmp_path)
    (source_dir / "groq_keys.txt").write_text("synthetic-groq-a\n", encoding="utf-8"); (source_dir / "openrouter_keys.txt").write_text("synthetic-openrouter-a\n", encoding="utf-8")
    result = connection_manager.sync_external_secret_sources(); records = _read(metadata)["connections"]
    assert result["groq"]["newly_imported"] == 1 and result["openrouter"]["newly_imported"] == 1
    assert records["GROQ-01"]["status"] == records["OR-01"]["status"] == "PENDING_ASSIGNMENT"; assert records["GROQ-01"]["active"] is False; assert records["OR-01"]["active"] is False
    assert records["GROQ-01"]["role"] is None


def test_C_repeated_startup_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    metadata, source_dir = _configure(monkeypatch, tmp_path); (source_dir / "groq_keys.txt").write_text("synthetic-groq-a\n", encoding="utf-8")
    first = connection_manager.sync_external_secret_sources(); ids_before = sorted(_read(metadata)["connections"]); second = connection_manager.sync_external_secret_sources(); ids_after = sorted(_read(metadata)["connections"])
    assert first["groq"]["newly_imported"] == 1 and second["groq"]["newly_imported"] == 0 and second["groq"]["already_known"] == 1 and ids_before == ids_after


def test_D_additive_growth(monkeypatch, tmp_path: Path) -> None:
    metadata, source_dir = _configure(monkeypatch, tmp_path); path = source_dir / "groq_keys.txt"; path.write_text("synthetic-groq-a\n", encoding="utf-8"); connection_manager.sync_external_secret_sources(); path.write_text("synthetic-groq-a\nsynthetic-groq-b\n", encoding="utf-8")
    result = connection_manager.sync_external_secret_sources(); assert result["groq"]["newly_imported"] == 1; assert set(_read(metadata)["connections"]) == {"GROQ-01", "GROQ-02"}


def test_E_source_omission_never_deletes(monkeypatch, tmp_path: Path) -> None:
    metadata, source_dir = _configure(monkeypatch, tmp_path); path = source_dir / "groq_keys.txt"; path.write_text("synthetic-groq-a\nsynthetic-groq-b\n", encoding="utf-8"); connection_manager.sync_external_secret_sources(); path.write_text("synthetic-groq-a\n", encoding="utf-8"); connection_manager.sync_external_secret_sources()
    assert set(_read(metadata)["connections"]) == {"GROQ-01", "GROQ-02"}


def test_F_invalid_line_is_isolated(monkeypatch, tmp_path: Path) -> None:
    metadata, source_dir = _configure(monkeypatch, tmp_path); (source_dir / "groq_keys.txt").write_text("synthetic-groq-a\nnot valid whitespace\n", encoding="utf-8"); result = connection_manager.sync_external_secret_sources()
    assert result["groq"]["invalid"] == result["groq"]["rejected"] == 1 and result["groq"]["newly_imported"] == 1 and list(_read(metadata)["connections"]) == ["GROQ-01"]


def test_G_provider_separation(monkeypatch, tmp_path: Path) -> None:
    _, source_dir = _configure(monkeypatch, tmp_path); (source_dir / "groq_keys.txt").write_text("same-synthetic-secret\n", encoding="utf-8"); (source_dir / "openrouter_keys.txt").write_text("same-synthetic-secret\n", encoding="utf-8"); result = connection_manager.sync_external_secret_sources()
    assert result["groq"]["newly_imported"] == result["openrouter"]["newly_imported"] == 1


def test_H_pending_assignment_cannot_become_routable(monkeypatch, tmp_path: Path) -> None:
    metadata, _ = _configure(monkeypatch, tmp_path); data = _read(metadata); data["connections"]["GROQ-01"] = {"connection_id":"GROQ-01","provider":"groq","key_fingerprint":"a"*64,"role":None,"status":"PENDING_ASSIGNMENT","active":False}; metadata.write_text(json.dumps(data), encoding="utf-8"); registry = connection_manager.load_registry()
    import pytest
    with pytest.raises(ValueError): connection_manager.enable_connection("GROQ-01", registry)
    assert registry["connections"]["GROQ-01"]["active"] is False


def test_I_no_secret_leakage(monkeypatch, tmp_path: Path) -> None:
    _, source_dir = _configure(monkeypatch, tmp_path); synthetic = "synthetic-secret-not-for-output"; (source_dir / "groq_keys.txt").write_text(synthetic + "\n", encoding="utf-8"); result = connection_manager.sync_external_secret_sources(); view = connection_read_model()
    assert synthetic not in repr(result) and synthetic not in repr(view) and view["raw_secrets_returned"] is False


def test_J_ui_has_no_secret_or_import_authority() -> None:
    paths = [Path("control_center.pyw"), Path("desktop_control_center.py"), Path("connection_control_center.py"), Path("control_center_operator_runtime.py"), Path("application_boundary.py")]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for symbol in FORBIDDEN_UI_SYMBOLS: assert symbol not in text, f"{path} still owns forbidden symbol: {symbol}"


def test_connections_page_contract_uses_core_read_model(monkeypatch, tmp_path: Path) -> None:
    _configure(monkeypatch, tmp_path); service = ControlCenterService(autowire_core=False)
    expected = {"connections":[{"connection_id":"GROQ-99","provider":"groq","status":"PENDING_ASSIGNMENT"}],"external_secret_sources":{"last_sync_at":"2030-01-01T00:00:00Z"},"raw_secrets_returned":False}
    monkeypatch.setattr("application_boundary.connection_read_model", lambda _runtime=None: expected); result = service.dispatch(ApplicationIntent("refresh_connections", {})); assert dict(result.data) == expected
