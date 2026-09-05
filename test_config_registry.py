from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
