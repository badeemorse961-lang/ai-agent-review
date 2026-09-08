from __future__ import annotations

"""Real Windows recovery acceptance for stable Leader connection rotation.

The test never mutates the repository's real config/registry.json, connections.json,
or production protected-secret store. It creates an isolated temporary sandbox, uses
Windows DPAPI for the sandbox credential store, and validates replacement credentials
against the real provider APIs.
"""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from connection_control_center import ConnectionControlCenterService
from connection_manager import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_DISABLED,
    LIFECYCLE_FAILED,
    connection_is_eligible,
    disable_connection,
    enable_connection,
    fingerprint,
    import_provider,
    remove_connection,
    replace_connection_credential,
    validate_connection,
)
from leader_router import LeaderRouter, LeaderUnavailable
from protected_secret_store import WindowsProtectedSecretStore


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _leader_ids(config: dict) -> list[str]:
    leader = config["architecture"]["leader"]
    return list(dict.fromkeys(leader["primary_pool"] + leader["failover_pool"]))


def _prepare_metadata(source: dict, leader_ids: list[str]) -> dict:
    data = json.loads(json.dumps(source))
    for connection_id in leader_ids:
        item = data["connections"][connection_id]
        item["status"] = LIFECYCLE_FAILED
        item["active"] = False
        item["credential_validated"] = False
        item["validation_required"] = True
        item["failure_reason"] = "acceptance: simulated expired leader credential"
    return data


def _make_health(config: dict) -> dict:
    leader = config["architecture"]["leader"]
    return {
        "provider": leader["provider"],
        "models": {
            leader["primary_model"]: {"provider": leader["provider"], "healthy": leader["primary_pool"], "failed": []},
            leader["failover_model"]: {"provider": leader["provider"], "healthy": leader["failover_pool"], "failed": []},
        },
    }


def run(repo_root: Path, replacement_txt: Path) -> None:
    if os.name != "nt":
        raise SystemExit("This acceptance must run on Windows so the protected store uses real DPAPI.")
    if replacement_txt.suffix.lower() != ".txt" or not replacement_txt.is_file():
        raise SystemExit("Replacement TXT must be an existing .txt file.")

    config_source = _load_json(repo_root / "config" / "registry.json")
    metadata_source = _load_json(repo_root / "connections.json")
    leader_ids = _leader_ids(config_source)
    if not leader_ids:
        raise AssertionError("Authoritative Leader pool is empty")

    with tempfile.TemporaryDirectory(prefix="ai-agent-leader-recovery-") as raw:
        sandbox = Path(raw)
        config_path = sandbox / "registry.json"
        metadata_path = sandbox / "connections.json"
        health_path = sandbox / "leader_health.json"
        state_path = sandbox / "leader_state.json"
        store_path = sandbox / "protected-secrets.bin"

        _dump(config_path, config_source)
        _dump(metadata_path, _prepare_metadata(metadata_source, leader_ids))
        _dump(health_path, _make_health(config_source))

        with patch("config_registry.REGISTRY_FILE", config_path), \
             patch("config_registry.CONNECTIONS_FILE", metadata_path), \
             patch("connection_manager.REGISTRY_FILE", metadata_path), \
             patch("connection_manager.AUTHORITATIVE_REGISTRY_FILE", config_path), \
             patch("leader_router.REGISTRY_FILE", config_path):
            store = WindowsProtectedSecretStore(path=store_path)
            for connection_id in leader_ids:
                store.put(connection_id, "openrouter", f"acceptance-old-{connection_id}", fingerprint(f"acceptance-old-{connection_id}"))

            # A: all existing leaders are failed; routing is fail-closed.
            router_down = LeaderRouter(health_file=health_path, state_file=state_path, registry_file=config_path)
            assert router_down.active_pool("ULTRA") == []
            with __import__("pytest").raises(LeaderUnavailable):
                router_down.acquire("ACCEPT-LEADER-DOWN")

            # B: rotate every existing stable ID from a named TXT source.
            metadata = _load_json(metadata_path)
            before_ids = list(metadata["connections"])
            before_assignments = (
                list(config_source["architecture"]["leader"]["primary_pool"]),
                list(config_source["architecture"]["leader"]["failover_pool"]),
            )
            for connection_id in leader_ids:
                replace_connection_credential(connection_id, replacement_txt, metadata, secret_store=store, persist=False)
            _dump(metadata_path, metadata)

            assert list(metadata["connections"]) == before_ids
            assert (
                config_source["architecture"]["leader"]["primary_pool"],
                config_source["architecture"]["leader"]["failover_pool"],
            ) == before_assignments

            # C: credentials exist, but rotation is not eligible before validation.
            for connection_id in leader_ids:
                item = metadata["connections"][connection_id]
                assert item["status"] == LIFECYCLE_DISABLED
                assert item["active"] is False
                assert item["validation_required"] is True
                assert store.has(connection_id)

            # D: real provider validation promotes assigned stable IDs back to ACTIVE.
            for connection_id in leader_ids:
                validate_connection(connection_id, registry=metadata, secret_store=store, persist=False)
            _dump(metadata_path, metadata)

            for connection_id in leader_ids:
                item = metadata["connections"][connection_id]
                assert item["status"] == LIFECYCLE_ACTIVE
                assert item["active"] is True
                assert item["credential_validated"] is True
                assert item["validation_required"] is False
                assert connection_is_eligible(connection_id, metadata)

            # E: the real LeaderRouter sees the recovered IDs again.
            recovered_router = LeaderRouter(health_file=health_path, state_file=state_path, registry_file=config_path)
            recovered_pool = recovered_router.active_pool("ULTRA")
            assert recovered_pool
            assert set(recovered_pool).issubset(set(leader_ids))
            lease = recovered_router.acquire("ACCEPT-RECOVERED")
            assert lease.account_id in leader_ids
            recovered_router.release("ACCEPT-RECOVERED")

            # F: protected credential persistence across store/service reconstruction.
            restarted_store = WindowsProtectedSecretStore(path=store_path)
            for connection_id in leader_ids:
                assert restarted_store.has(connection_id)

            service = ConnectionControlCenterService(secret_store=restarted_store, autowire_core=False)
            view = service.dispatch(__import__("application_boundary").ApplicationIntent("refresh_connections", {}))
            returned = {item["connection_id"]: item for item in view.data["connections"]}
            for connection_id in leader_ids:
                assert returned[connection_id]["credential_present"] is True
                assert returned[connection_id]["ready_state"] == "READY"

            # G: re-import same replacement TXT; no duplicates or identity changes.
            second = import_provider("openrouter", replacement_txt, metadata, "OR", secret_store=restarted_store, persist=False)
            assert second.imported_count == 0
            assert second.already_present_count == len(leader_ids)
            assert set(metadata["connections"]) == set(before_ids)

            # H: add one genuinely new credential; it is stored only and remains unassigned.
            new_txt = sandbox / "new.txt"
            new_txt.write_text("new-recovery-key\n", encoding="utf-8")
            added = import_provider("openrouter", new_txt, metadata, "OR", secret_store=restarted_store, persist=False)
            assert added.imported_count == 1
            new_id = added.connection_ids[0]
            assert new_id not in leader_ids
            assert metadata["connections"][new_id]["status"] == LIFECYCLE_DISABLED
            assert not metadata["connections"][new_id]["active"]
            assert new_id not in config_source["architecture"]["leader"]["primary_pool"]
            assert new_id not in config_source["architecture"]["leader"]["failover_pool"]

            # I: disable/enable preserves the protected credential.
            disable_connection(leader_ids[0], metadata, persist=False)
            assert metadata["connections"][leader_ids[0]]["status"] == LIFECYCLE_DISABLED
            assert restarted_store.has(leader_ids[0])
            enable_connection(leader_ids[0], metadata, persist=False)
            assert metadata["connections"][leader_ids[0]]["status"] == LIFECYCLE_ACTIVE

            # J: assigned removal is blocked and cannot rewrite authoritative config.
            with __import__("pytest").raises(ValueError, match="approved Core configuration authority"):
                remove_connection(leader_ids[0], registry=metadata, secret_store=restarted_store, persist=False)
            assert restarted_store.has(leader_ids[0])

            # K: explicit removal of the genuinely new unassigned connection.
            remove_connection(new_id, registry=metadata, secret_store=restarted_store, persist=False)
            assert metadata["connections"][new_id]["status"] == "REMOVED"
            assert not restarted_store.has(new_id)
            for connection_id in leader_ids:
                assert restarted_store.has(connection_id)

    print("Windows Leader Recovery Acceptance: PASS")
    print(f"Leader stable IDs recovered: {len(leader_ids)}")
    print("Protected credential persistence: PASS")
    print("Stable identity / assignment preservation: PASS")
    print("No Dynamic Auto-Assignment: PASS")
    print("Assigned removal authority protection: PASS")
    print("New-key tombstone removal: PASS")
    print("Raw secrets printed: NO")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--replacement-txt", type=Path, required=True)
    args = parser.parse_args()
    run(args.repo_root.resolve(), args.replacement_txt.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
