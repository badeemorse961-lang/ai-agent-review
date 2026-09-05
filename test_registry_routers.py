from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config_registry import validate_registry
from leader_failover import LeaderFailover
from leader_router import LeaderRouter, LeaderUnavailable
from worker_router import NoWorkerAvailable, WorkerRouter


class RegistryDrivenRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write(self, name: str, payload: dict) -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        return path

    def _leader_health(self) -> Path:
        registry = validate_registry()
        leader = registry["architecture"]["leader"]
        return self._write(
            "leader_health.json",
            {
                "models": {
                    leader["primary_model"]: {
                        "healthy": list(leader["primary_pool"]),
                        "failed": [],
                    },
                    leader["failover_model"]: {
                        "healthy": list(leader["failover_pool"]),
                        "failed": [],
                    },
                }
            },
        )

    def _worker_health(self) -> Path:
        registry = validate_registry()
        workers = registry["architecture"]["workers"]
        all_ids = [
            worker_id
            for pool in workers["roles"].values()
            for worker_id in pool
        ]
        return self._write(
            "worker_health.json",
            {"healthy": all_ids, "failed": []},
        )

    def test_leader_router_reads_registry_configuration(self) -> None:
        registry = validate_registry()
        leader = registry["architecture"]["leader"]
        router = LeaderRouter(
            health_file=self._leader_health(),
            state_file=self.root / "leader_state.json",
        )

        self.assertEqual(router.primary_pool, leader["primary_pool"])
        self.assertEqual(router.failover_pool, leader["failover_pool"])
        self.assertEqual(router.primary_model, leader["primary_model"])
        self.assertEqual(router.failover_model, leader["failover_model"])

    def test_worker_router_reads_registry_configuration(self) -> None:
        registry = validate_registry()
        workers = registry["architecture"]["workers"]
        router = WorkerRouter(
            health_file=self._worker_health(),
            state_file=self.root / "worker_state.json",
        )

        self.assertEqual(router.provider, workers["provider"])
        self.assertEqual(router.model, workers["model"])
        self.assertEqual(router.worker_pools, workers["roles"])

    def test_leader_router_fails_over_after_primary_exhaustion(self) -> None:
        router = LeaderRouter(
            health_file=self._leader_health(),
            state_file=self.root / "leader_state.json",
        )

        for index in range(len(router.primary_pool)):
            task_id = f"primary-{index}"
            lease = router.acquire(task_id)
            self.assertEqual(lease.tier, "ULTRA")
            router.fail_current_leader(task_id)

        failover = router.acquire("super-1")
        self.assertEqual(failover.tier, "SUPER")
        self.assertEqual(failover.model, router.failover_model)

    def test_leader_failover_reset_preserves_legacy_active_semantics(self) -> None:
        manager = LeaderFailover(
            health_file=self._leader_health(),
            state_file=self.root / "leader_failover_state.json",
        )

        first = manager.reset()

        self.assertEqual(first, manager.primary_pool["connections"][0])
        self.assertEqual(manager.current_connection(), first)
        self.assertEqual(manager.current_model(), manager.primary_model)
        self.assertEqual(manager.current_tier(), "primary")
        self.assertEqual(manager.state(), "READY")

        manager.failover("compatibility_test_failure")

    def test_worker_standby_is_used_only_after_role_exhaustion(self) -> None:
        router = WorkerRouter(
            health_file=self._worker_health(),
            state_file=self.root / "worker_state.json",
        )

        for worker_id in router.worker_pools["coder"]:
            router.mark_failed(worker_id)

        standby = router.acquire("coder", "standby-task")
        self.assertTrue(standby.standby)
        self.assertIn(
            standby.worker_id,
            router.worker_pools["standby"],
        )

        router.release("standby-task")
        for worker_id in router.worker_pools["coder"]:
            router.mark_failed(worker_id)
        router.mark_failed(standby.worker_id)

        with self.assertRaises(NoWorkerAvailable):
            router.acquire("coder", "standby-exhausted")


class RouterExhaustionContractTests(unittest.TestCase):
    def test_leader_unavailable_type_is_explicit(self) -> None:
        self.assertTrue(issubclass(LeaderUnavailable, Exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
