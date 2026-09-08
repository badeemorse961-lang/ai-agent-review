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
    replace_connection_credential,
    resolve_secret_file,
    save_registry,
    validate_connection,
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
                "credential_validated": True,
                "validation_required": False,
            }
            for connection_id in ids
        },
    }


def write_worker_auth(path: Path, connection_ids: list[str]) -> None:
    path.write_text(json.dumps({"architecture": {"workers": {"roles": {"coder": connection_ids}}}}), encoding="utf-8")


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
    assert registry["connections"]["GROQ-02"]["status"] == LIFECYCLE_DISABLED


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
    assert first.already_present_count == 1 and second.already_present_count == 1
    assert first.imported_count == 0 and second.imported_count == 0
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


def test_rotation_preserves_id_changes_fingerprint_and_requires_validation(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01"])
    store = MemorySecretStore()
    old_fp = registry["connections"]["GROQ-01"]["key_fingerprint"]
    store.put("GROQ-01", "groq", "secret-GROQ-01", old_fp)
    source = tmp_path / "rotation.txt"
    source.write_text("GROQ-01=new-secret-value\n", encoding="utf-8")
    summary = replace_connection_credential("GROQ-01", source, registry, secret_store=store, persist=False)
    item = registry["connections"]["GROQ-01"]
    assert summary.imported_count == 1
    assert set(registry["connections"]) == {"GROQ-01"}
    assert item["key_fingerprint"] == fingerprint("new-secret-value")
    assert item["key_fingerprint"] != old_fp
    assert item["status"] == LIFECYCLE_DISABLED
    assert item["validation_required"] is True
    assert item["credential_validated"] is False


def test_rotation_duplicate_fingerprint_is_rejected_without_mutation(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01", "GROQ-02"])
    store = MemorySecretStore()
    for connection_id in registry["connections"]:
        secret = f"secret-{connection_id}"
        store.put(connection_id, "groq", secret, fingerprint(secret))
    source = tmp_path / "duplicate.txt"
    source.write_text("GROQ-01=secret-GROQ-02\n", encoding="utf-8")
    before = dict(registry["connections"]["GROQ-01"])
    with pytest.raises(ValueError, match="already belongs"):
        replace_connection_credential("GROQ-01", source, registry, secret_store=store, persist=False)
    assert registry["connections"]["GROQ-01"] == before
    assert store.get("GROQ-01", "groq") == "secret-GROQ-01"


def test_failed_rotation_recovers_only_after_successful_validation(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01"])
    registry["connections"]["GROQ-01"].update({"status": LIFECYCLE_FAILED, "active": False, "credential_validated": False, "validation_required": True})
    store = MemorySecretStore()
    old_fp = registry["connections"]["GROQ-01"]["key_fingerprint"]
    store.put("GROQ-01", "groq", "old", old_fp)
    source = tmp_path / "recover.txt"
    source.write_text("GROQ-01=replacement\n", encoding="utf-8")
    replace_connection_credential("GROQ-01", source, registry, secret_store=store, persist=False)
    assert registry["connections"]["GROQ-01"]["status"] == LIFECYCLE_DISABLED
    assert not connection_is_eligible("GROQ-01", registry)
    auth = tmp_path / "registry.json"
    write_worker_auth(auth, ["GROQ-01"])
    with patch("connection_manager.AUTHORITATIVE_REGISTRY_FILE", auth):
        validate_connection("GROQ-01", registry=registry, secret_store=store, validator=lambda *_: None, persist=False)
    assert registry["connections"]["GROQ-01"]["status"] == LIFECYCLE_ACTIVE
    assert registry["connections"]["GROQ-01"]["credential_validated"] is True
    assert registry["connections"]["GROQ-01"]["validation_required"] is False
    assert connection_is_eligible("GROQ-01", registry)


def test_validate_unassigned_connection_stays_disabled(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01"])
    store = MemorySecretStore()
    secret = "secret-GROQ-01"
    store.put("GROQ-01", "groq", secret, fingerprint(secret))
    auth = tmp_path / "registry.json"
    write_worker_auth(auth, ["GROQ-02"])
    with patch("connection_manager.AUTHORITATIVE_REGISTRY_FILE", auth):
        validate_connection("GROQ-01", registry=registry, secret_store=store, validator=lambda *_: None, persist=False)
    assert registry["connections"]["GROQ-01"]["status"] == LIFECYCLE_DISABLED
    assert not connection_is_eligible("GROQ-01", registry)
    assert store.has("GROQ-01")


def test_disable_and_enable_preserve_secret(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01"])
    store = MemorySecretStore()
    secret = "secret-GROQ-01"
    store.put("GROQ-01", "groq", secret, fingerprint(secret))
    auth = tmp_path / "registry.json"
    write_worker_auth(auth, ["GROQ-01"])
    metadata = tmp_path / "connections.json"
    with patch("connection_manager.AUTHORITATIVE_REGISTRY_FILE", auth), patch("connection_manager.REGISTRY_FILE", metadata):
        disable_connection("GROQ-01", registry, persist=True)
        assert get_connection_status("GROQ-01", registry) == LIFECYCLE_DISABLED
        assert store.get("GROQ-01", "groq") == secret
        enable_connection("GROQ-01", registry, persist=True)
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


def test_remove_assigned_connection_is_blocked_without_rewriting_authority(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01", "GROQ-02"])
    store = MemorySecretStore()
    for connection_id in registry["connections"]:
        secret = f"secret-{connection_id}"
        store.put(connection_id, "groq", secret, fingerprint(secret))
    auth = tmp_path / "registry.json"
    write_worker_auth(auth, ["GROQ-01", "GROQ-02"])
    before = auth.read_text(encoding="utf-8")
    with patch("connection_manager.AUTHORITATIVE_REGISTRY_FILE", auth):
        with pytest.raises(ValueError, match="approved Core configuration authority"):
            remove_connection("GROQ-01", registry=registry, secret_store=store, persist=True)
    assert auth.read_text(encoding="utf-8") == before
    assert store.has("GROQ-01")
    assert registry["connections"]["GROQ-01"]["status"] == LIFECYCLE_ACTIVE


def test_remove_unassigned_deletes_only_selected_and_tombstones(tmp_path: Path) -> None:
    registry = registry_with(["GROQ-01", "GROQ-02"])
    store = MemorySecretStore()
    for connection_id in registry["connections"]:
        secret = f"secret-{connection_id}"
        store.put(connection_id, "groq", secret, fingerprint(secret))
    auth = tmp_path / "registry.json"
    write_worker_auth(auth, ["GROQ-02"])
    metadata = tmp_path / "connections.json"
    with patch("connection_manager.AUTHORITATIVE_REGISTRY_FILE", auth), patch("connection_manager.REGISTRY_FILE", metadata):
        assert remove_connection("GROQ-01", registry=registry, secret_store=store, persist=True)
    assert registry["connections"]["GROQ-01"]["status"] == "REMOVED"
    assert "GROQ-02" in registry["connections"]
    assert not store.has("GROQ-01") and store.has("GROQ-02")


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
