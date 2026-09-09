from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import connection_manager
from config_registry import validate_registry


VALID_REGISTRY = {
    "schema_version": 1,
    "registry_id": "test",
    "architecture": {
        "leader": {
            "provider": "openrouter",
            "primary_model": "leader-primary",
            "failover_model": "leader-failover",
            "safe_stop_on_exhaustion": True,
            "primary_pool": ["OR-01"],
            "failover_pool": ["OR-01"],
        },
        "workers": {
            "provider": "groq",
            "model": "worker-model",
            "safe_stop_on_required_role_exhaustion": True,
            "roles": {
                "coder": ["GROQ-01"],
                "standby": [],
            },
        },
    },
    "connection_sources": {
        "metadata_file": "connections.json",
        "role_source": "this registry",
        "health_source": "runtime",
        "runtime_state_source": "local runtime state",
    },
    "policies": {
        "connection_ids_must_be_unique": True,
        "connection_must_belong_to_exactly_one_assignment": True,
        "leader_pools_must_use_leader_provider": True,
        "worker_pools_must_use_worker_provider": True,
        "runtime_state_must_not_be_committed": True,
        "secrets_must_not_be_committed": True,
        "pool_sizes_are_not_hardcoded": True,
    },
}


def metadata(connection_id: str, provider: str, secret: str, status: str = "VALIDATED") -> dict[str, object]:
    return {
        "connection_id": connection_id,
        "provider": provider,
        "key_fingerprint": connection_manager.fingerprint(secret),
        "role": None,
        "status": status,
        "active": False,
    }


def write_fixture(
    root: Path,
    *,
    registry: dict[str, object] | None = None,
    sources: dict[str, str | None] | None = None,
) -> tuple[Path, Path, Path, Path]:
    connections_path = root / "connections.json"
    registry_path = root / "registry.json"
    source_dir = root / "secrets"
    source_dir.mkdir(exist_ok=True)
    registry_path.write_text(
        json.dumps(registry or {"version": 3, "connections": {}}, indent=2),
        encoding="utf-8",
    )
    connections_path.write_text(
        json.dumps(
            {
                "version": 3,
                "role_source": "config/registry.json",
                "connections": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    for filename, content in (sources or {}).items():
        if content is not None:
            (source_dir / filename).write_text(content, encoding="utf-8")
    return (
        connections_path,
        registry_path,
        source_dir / "groq_keys.txt",
        source_dir / "openrouter_keys.txt",
    )


class ExternalSecretSourceSyncTests(unittest.TestCase):
    def test_missing_sources_are_non_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            connections_path, _, _, _ = write_fixture(root)
            with patch.object(connection_manager, "REGISTRY_FILE", connections_path), patch.dict(
                os.environ,
                {"AI_AGENT_SECRET_DIR": str(root / "missing")},
                clear=False,
            ):
                results = connection_manager.sync_external_secret_sources()

            self.assertFalse(results["groq"]["source_exists"])
            self.assertFalse(results["openrouter"]["source_exists"])
            self.assertEqual(results["groq"]["newly_imported"], 0)
            self.assertEqual(results["openrouter"]["newly_imported"], 0)

    def test_fifteen_new_groq_keys_are_imported_additively(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            keys = "\n".join(f"groq-secret-{index}" for index in range(1, 16)) + "\n"
            connections_path, _, _, _ = write_fixture(root, sources={"groq_keys.txt": keys})
            with patch.object(connection_manager, "REGISTRY_FILE", connections_path), patch.dict(
                os.environ,
                {"AI_AGENT_SECRET_DIR": str(root / "secrets")},
                clear=False,
            ):
                results = connection_manager.sync_external_secret_sources()
                saved = connection_manager.load_registry()

            self.assertEqual(results["groq"]["newly_imported"], 15)
            self.assertEqual(len(saved["connections"]), 15)
            self.assertEqual(saved["connections"]["GROQ-01"]["status"], "PENDING_ASSIGNMENT")
            self.assertTrue(all("groq-secret" not in str(item) for item in saved["connections"].values()))

    def test_repeat_sync_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            keys = "alpha\nbeta\ngamma\n"
            connections_path, _, _, _ = write_fixture(root, sources={"groq_keys.txt": keys})
            with patch.object(connection_manager, "REGISTRY_FILE", connections_path), patch.dict(
                os.environ,
                {"AI_AGENT_SECRET_DIR": str(root / "secrets")},
                clear=False,
            ):
                first = connection_manager.sync_external_secret_sources()
                second = connection_manager.sync_external_secret_sources()
                saved = connection_manager.load_registry()

            self.assertEqual(first["groq"]["newly_imported"], 3)
            self.assertEqual(second["groq"]["newly_imported"], 0)
            self.assertEqual(second["groq"]["already_known"], 3)
            self.assertEqual(sorted(saved["connections"]), ["GROQ-01", "GROQ-02", "GROQ-03"])

    def test_three_added_keys_import_only_three(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "secrets"
            path.mkdir()
            groq_file = path / "groq_keys.txt"
            groq_file.write_text("a\nb\n", encoding="utf-8")
            connections_path, _, _, _ = write_fixture(root)
            with patch.object(connection_manager, "REGISTRY_FILE", connections_path), patch.dict(
                os.environ,
                {"AI_AGENT_SECRET_DIR": str(path)},
                clear=False,
            ):
                first = connection_manager.sync_external_secret_sources()
                groq_file.write_text("a\nb\nc\nd\ne\n", encoding="utf-8")
                second = connection_manager.sync_external_secret_sources()
                saved = connection_manager.load_registry()

            self.assertEqual(first["groq"]["newly_imported"], 2)
            self.assertEqual(second["groq"]["newly_imported"], 3)
            self.assertEqual(sorted(saved["connections"]), ["GROQ-01", "GROQ-02", "GROQ-03", "GROQ-04", "GROQ-05"])

    def test_removed_source_line_does_not_remove_connection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            secret_dir = root / "secrets"
            secret_dir.mkdir()
            groq_file = secret_dir / "groq_keys.txt"
            groq_file.write_text("a\nb\nc\n", encoding="utf-8")
            connections_path, _, _, _ = write_fixture(root)
            with patch.object(connection_manager, "REGISTRY_FILE", connections_path), patch.dict(
                os.environ,
                {"AI_AGENT_SECRET_DIR": str(secret_dir)},
                clear=False,
            ):
                connection_manager.sync_external_secret_sources()
                groq_file.write_text("a\nc\n", encoding="utf-8")
                connection_manager.sync_external_secret_sources()
                saved = connection_manager.load_registry()

            self.assertIn("GROQ-02", saved["connections"])
            self.assertEqual(saved["connections"]["GROQ-02"]["status"], "PENDING_ASSIGNMENT")

    def test_invalid_line_does_not_block_valid_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            connections_path, _, _, _ = write_fixture(
                root,
                sources={"groq_keys.txt": "valid-one\ninvalid line with spaces\nvalid-two\n"},
            )
            with patch.object(connection_manager, "REGISTRY_FILE", connections_path), patch.dict(
                os.environ,
                {"AI_AGENT_SECRET_DIR": str(root / "secrets")},
                clear=False,
            ):
                result = connection_manager.sync_external_secret_sources()["groq"]
                saved = connection_manager.load_registry()

            self.assertEqual(result["invalid"], 1)
            self.assertEqual(result["newly_imported"], 2)
            self.assertEqual(len(saved["connections"]), 2)

    def test_groq_and_openrouter_remain_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            connections_path, _, _, _ = write_fixture(
                root,
                sources={
                    "groq_keys.txt": "groq-a\ngroq-b\n",
                    "openrouter_keys.txt": "or-a\nor-b\n",
                },
            )
            with patch.object(connection_manager, "REGISTRY_FILE", connections_path), patch.dict(
                os.environ,
                {"AI_AGENT_SECRET_DIR": str(root / "secrets")},
                clear=False,
            ):
                connection_manager.sync_external_secret_sources()
                saved = connection_manager.load_registry()

            self.assertEqual(
                {item["provider"] for item in saved["connections"].values() if item["connection_id"].startswith("GROQ-")},
                {"groq"},
            )
            self.assertEqual(
                {item["provider"] for item in saved["connections"].values() if item["connection_id"].startswith("OR-")},
                {"openrouter"},
            )

    def test_legacy_repo_path_is_not_used(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            connections_path, _, _, _ = write_fixture(root)
            legacy = root / "groq_keys.txt"
            legacy.write_text("legacy-secret", encoding="utf-8")
            with patch.object(connection_manager, "BASE_DIR", root), patch.object(
                connection_manager, "REGISTRY_FILE", connections_path
            ), patch.dict(
                os.environ,
                {"AI_AGENT_SECRET_DIR": str(root / "missing")},
                clear=False,
            ):
                os.environ.pop("AI_AGENT_ALLOW_LEGACY_SECRET_PATH", None)
                results = connection_manager.sync_external_secret_sources()

            self.assertFalse(results["groq"]["source_exists"])
            self.assertEqual(results["groq"]["newly_imported"], 0)

    def test_diagnostics_never_contain_secret_values(self) -> None:
        secret = "diagnostic-secret-never-print"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            connections_path, _, _, _ = write_fixture(
                root,
                sources={"groq_keys.txt": secret + "\n"},
            )
            with patch.object(connection_manager, "REGISTRY_FILE", connections_path), patch.dict(
                os.environ,
                {"AI_AGENT_SECRET_DIR": str(root / "secrets")},
                clear=False,
            ):
                report = connection_manager.sync_external_secret_sources()
                serialized = json.dumps(report)

            self.assertNotIn(secret, serialized)
            self.assertIn("newly_imported", serialized)

    def test_pending_metadata_remains_valid_under_authoritative_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry_path = root / "config_registry.json"
            connections_path = root / "connections.json"
            registry_path.write_text(json.dumps(VALID_REGISTRY, indent=2), encoding="utf-8")
            connections = {
                "version": 3,
                "role_source": "config/registry.json",
                "connections": {
                    "OR-01": metadata("OR-01", "openrouter", "or-secret"),
                    "GROQ-01": metadata("GROQ-01", "groq", "groq-secret"),
                    "GROQ-02": metadata(
                        "GROQ-02", "groq", "pending-secret", "PENDING_ASSIGNMENT"
                    ),
                },
            }
            connections_path.write_text(json.dumps(connections, indent=2), encoding="utf-8")
            with patch("config_registry.REGISTRY_FILE", registry_path), patch(
                "config_registry.CONNECTIONS_FILE", connections_path
            ):
                validate_registry()


if __name__ == "__main__":
    unittest.main(verbosity=2)
