from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config_registry
from config_registry import (
    RegistryError,
    get_leader_pool,
    get_worker_pools,
    validate_registry,
)


class ConfigurationRegistryTests(unittest.TestCase):
    def test_registry_is_valid(self) -> None:
        registry = validate_registry()
        self.assertEqual(registry["schema_version"], 1)

    def test_leader_pools_are_dynamic_and_disjoint_from_workers(self) -> None:
        primary = get_leader_pool("primary")
        failover = get_leader_pool("failover")
        workers = get_worker_pools()

        self.assertTrue(primary)
        self.assertEqual(set(primary), set(failover))

        worker_ids = {
            worker_id
            for ids in workers.values()
            for worker_id in ids
        }
        self.assertTrue(set(primary).isdisjoint(worker_ids))

    def test_worker_ids_are_globally_unique(self) -> None:
        workers = get_worker_pools()
        all_ids = [worker_id for ids in workers.values() for worker_id in ids]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_unknown_tier_rejected(self) -> None:
        with self.assertRaises(RegistryError):
            get_leader_pool("unknown")

    def _validate_temp_connection_metadata(self, mutate) -> None:
        registry = config_registry.load_registry()
        connections = config_registry.load_connections()
        mutate(connections["connections"])

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry_path = root / "registry.json"
            connections_path = root / "connections.json"
            registry_path.write_text(
                json.dumps(registry), encoding="utf-8"
            )
            connections_path.write_text(
                json.dumps(connections), encoding="utf-8"
            )
            with patch.object(config_registry, "REGISTRY_FILE", registry_path), patch.object(
                config_registry, "CONNECTIONS_FILE", connections_path
            ):
                with self.assertRaises(RegistryError):
                    validate_registry()

    def test_unassigned_connection_is_rejected(self) -> None:
        def add_unassigned(connections) -> None:
            connections["GROQ-99"] = {
                "connection_id": "GROQ-99",
                "provider": "groq",
                "key_fingerprint": "a" * 64,
                "role": None,
                "status": "VALIDATED",
                "active": False,
            }

        self._validate_temp_connection_metadata(add_unassigned)

    def test_connection_metadata_key_identity_must_match(self) -> None:
        def break_identity(connections) -> None:
            connections["OR-01"]["connection_id"] = "OR-99"

        self._validate_temp_connection_metadata(break_identity)


if __name__ == "__main__":
    unittest.main()
