from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from connection_manager import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_DISABLED,
    LIFECYCLE_FAILED,
    PROVIDER_PREFIXES,
    connection_is_eligible,
    disable_connection,
    enable_connection,
    fingerprint,
    get_connection_status,
    import_provider,
    remove_connection,
    resolve_secret_file,
    save_registry,
)
from protected_secret_store import MemorySecretStore


def registry_with(ids: list[str]) -> dict:
    return {
        "version": 2,
        "role_source": "config/registry.json",
        "connections": {
            connection_id: {
                "connection_id": connection_id,
                "provider": "groq",
                "key_fingerprint": fingerprint(f"secret-{connection_id}"),
                "role": None,
                "status": LIFECYCLE_ACTIVE,
                "active": True,
            }
            for connection_id in ids
        },
    }


def test_import_is_additive_and_preserves_existing(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01"])
    store = MemorySecretStore()
    store.put("GROQ-01", "groq", "secret-GROQ-01", registry["connections"]["GROQ-01"]["key_fingerprint"])
    source = tmp_path / "new.txt"
    source.write_text("new-secret\n", encoding="utf-8")

    summary = import_provider("groq", source, registry, PROVIDER_PREFIXES["groq"], secret_store=store, persist=False)

    assert summary.imported_count == 1
    assert set(registry["connections"]) == {"GROQ-01", "GROQ-02"}
    assert store.has("GROQ-01") and store.has("GROQ-02")


def test_duplicate_import_is_idempotent_by_fingerprint(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01"])
    store = MemorySecretStore()
    secret = "duplicate-secret"
    fp = fingerprint(secret)
    registry["connections"]["GROQ-01"]["key_fingerprint"] = fp
    store.put("GROQ-01", "groq", secret, fp)
    source = tmp_path / "source.txt"
    source.write_text(f"{secret}\n", encoding="utf-8")

    first = import_provider("groq", source, registry, PROVIDER_PREFIXES["groq"], secret_store=store, persist=False)
    second = import_provider("groq", source, registry, PROVIDER_PREFIXES["groq"], secret_store=store, persist=False)

    assert first.already_present_count == 1
    assert second.already_present_count == 1
    assert first.imported_count == 0
    assert second.imported_count == 0
    assert list(registry["connections"]) == ["GROQ-01"]


def test_import_omission_never_disables_previous_key(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01", "GROQ-02"])
    store = MemorySecretStore()
    for connection_id in registry["connections"]:
        secret = f"secret-{connection_id}"
        store.put(connection_id, "groq", secret, fingerprint(secret))
    source = tmp_path / "subset.txt"
    source.write_text("secret-GROQ-02\n", encoding="utf-8")

    import_provider("groq", source, registry, PROVIDER_PREFIXES["groq"], secret_store=store, persist=False)

    assert get_connection_status("GROQ-01", registry) == LIFECYCLE_ACTIVE
    assert connection_is_eligible("GROQ-01", registry)


def test_disable_and_enable_preserve_secret(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01"])
    store = MemorySecretStore()
    secret = "secret-GROQ-01"
    store.put("GROQ-01", "groq", secret, fingerprint(secret))
    auth = tmp_path / "registry.json"
    auth.write_text(json.dumps({"architecture": {"workers": {"roles": {"coder": ["GROQ-01"]}}}}), encoding="utf-8")

    with patch("connection_manager.AUTHORITATIVE_REGISTRY_FILE", auth):
        disable_connection("GROQ-01", registry, persist=False)
        assert get_connection_status("GROQ-01", registry) == LIFECYCLE_DISABLED
        assert not connection_is_eligible("GROQ-01", registry)
        enable_connection("GROQ-01", registry, persist=False)

    assert get_connection_status("GROQ-01", registry) == LIFECYCLE_ACTIVE
    assert store.get("GROQ-01", "groq") == secret


def test_failed_does_not_delete_secret() -> None:
    registry = registry_with(["GROQ-01"])
    store = MemorySecretStore()
    secret = "secret-GROQ-01"
    store.put("GROQ-01", "groq", secret, fingerprint(secret))
    from connection_manager import mark_connection_failed

    mark_connection_failed("GROQ-01", reason="expired", registry=registry, persist=False)

    assert get_connection_status("GROQ-01", registry) == LIFECYCLE_FAILED
    assert store.get("GROQ-01", "groq") == secret


def test_remove_deletes_only_selected_and_updates_authoritative_registry(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01", "GROQ-02"])
    store = MemorySecretStore()
    for connection_id in registry["connections"]:
        secret = f"secret-{connection_id}"
        store.put(connection_id, "groq", secret, fingerprint(secret))
    auth = tmp_path / "registry.json"
    auth.write_text(json.dumps({"architecture": {"workers": {"roles": {"coder": ["GROQ-01", "GROQ-02"]}}}}), encoding="utf-8")

    with patch("connection_manager.AUTHORITATIVE_REGISTRY_FILE", auth):
        assert remove_connection("GROQ-01", registry=registry, secret_store=store, persist=True)

    assert registry["connections"]["GROQ-01"]["status"] == "REMOVED"
    assert "GROQ-02" in registry["connections"]
    assert not store.has("GROQ-01")
    assert store.has("GROQ-02")
    updated = json.loads(auth.read_text(encoding="utf-8"))
    assert updated["architecture"]["workers"]["roles"]["coder"] == ["GROQ-02"]


def test_resolve_secret_file_is_only_an_import_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "groq_keys.txt").write_text("secret-a\n", encoding="utf-8")
    monkeypatch.setenv("AI_AGENT_SECRET_DIR", str(source_dir))
    assert resolve_secret_file("groq") == source_dir / "groq_keys.txt"


def test_save_registry_keeps_only_metadata(tmp_path: Path) -> None:
    path = tmp_path / "connections.json"
    with patch("connection_manager.REGISTRY_FILE", path):
        save_registry({"version": 2, "connections": {"GROQ-01": {"key_fingerprint": "a" * 64}}})
    assert "secret" not in path.read_text(encoding="utf-8").lower()
