from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config_registry import validate_registry
from leader_failover import LeaderFailover
from leader_router import LeaderConfigurationError, LeaderRouter, LeaderUnavailable
from worker_router import ConfigurationError, NoWorkerAvailable, WorkerRouter


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

    def test_leader_health_ignores_unknown_id_even_when_marked_healthy(self) -> None:
        registry = validate_registry()
        leader = registry["architecture"]["leader"]
        health = self._write(
            "leader_health_unknown.json",
            {
                "provider": leader["provider"],
                "models": {
                    leader["primary_model"]: {
                        "healthy": list(leader["primary_pool"]) + ["OR-999"],
                        "failed": [],
                    },
                    leader["failover_model"]: {
                        "healthy": list(leader["failover_pool"]),
                        "failed": [],
                    },
                },
            },
        )
        router = LeaderRouter(health_file=health, state_file=self.root / "state.json")

        self.assertNotIn("OR-999", router.external_healthy_by_model[leader["primary_model"]])
        self.assertNotIn("OR-999", router.active_pool("ULTRA"))

    def test_leader_health_rejects_wrong_provider(self) -> None:
        registry = validate_registry()
        leader = registry["architecture"]["leader"]
        health = self._leader_health()
        payload = json.loads(health.read_text(encoding="utf-8"))
        payload["provider"] = "groq"
        health.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaises(LeaderConfigurationError):
            LeaderRouter(health_file=health, state_file=self.root / "state.json")

    def test_leader_state_rejects_cross_tier_lease(self) -> None:
        registry = validate_registry()
        leader = registry["architecture"]["leader"]
        health = self._leader_health()
        state = self._write(
            "leader_state_cross_tier.json",
            {
                "runtime_failed_by_model": {},
                "leases": {
                    "task": {
                        "provider": leader["provider"],
                        "account_id": leader["primary_pool"][0],
                        "model": leader["failover_model"],
                        "tier": "SUPER",
                        "task_id": "task",
                        "leased_at": 1.0,
                    }
                },
                "active_tier": "SUPER",
                "active_account": leader["primary_pool"][0],
            },
        )
        router = LeaderRouter(health_file=health, state_file=state)

        self.assertEqual(router.leases, {})
        self.assertIsNone(router.active_tier)
        self.assertIsNone(router.active_account)

    def test_worker_health_ignores_unknown_and_wrong_provider_entries(self) -> None:
        registry = validate_registry()
        workers = registry["architecture"]["workers"]
        first = workers["roles"]["coder"][0]
        health = self._write(
            "worker_health_adversarial.json",
            {
                "provider": workers["provider"],
                "healthy": ["GROQ-999"],
                "failed": [],
                "results": {
                    "GROQ-999": {
                        "provider": "groq",
                        "model": workers["model"],
                        "status": "OK",
                    },
                    first: {
                        "provider": "openrouter",
                        "model": workers["model"],
                        "status": "OK",
                    },
                },
            },
        )
        router = WorkerRouter(health_file=health, state_file=self.root / "state.json")

        self.assertNotIn(first, router.external_healthy_connections)
        self.assertNotIn("GROQ-999", router.external_healthy_connections)
        self.assertNotIn("GROQ-999", router.external_failed_connections)

    def test_worker_state_rejects_wrong_role_lease_and_stale_standby_metadata(self) -> None:
        registry = validate_registry()
        workers = registry["architecture"]["workers"]
        coder = workers["roles"]["coder"][0]
        standby = workers["roles"]["standby"][0]
        state = self._write(
            "worker_state_adversarial.json",
            {
                "leases": {
                    "bad-role": {
                        "worker_id": coder,
                        "role": "reviewer",
                        "task_id": "bad-role",
                        "leased_at": 1.0,
                        "standby": False,
                    },
                    "bad-standby": {
                        "worker_id": coder,
                        "role": "coder",
                        "task_id": "bad-standby",
                        "leased_at": 1.0,
                        "standby": True,
                    },
                    "good-standby": {
                        "worker_id": standby,
                        "role": "coder",
                        "task_id": "good-standby",
                        "leased_at": 1.0,
                        "standby": True,
                    },
                },
                "active_standby_for": "debugger",
                "active_standby_worker": standby,
            },
        )
        router = WorkerRouter(
            health_file=self._worker_health(),
            state_file=state,
        )

        self.assertNotIn("bad-role", router.leases)
        self.assertNotIn("bad-standby", router.leases)
        self.assertIn("good-standby", router.leases)
        self.assertIsNone(router.active_standby_for)
        self.assertIsNone(router.active_standby_worker)

    def test_worker_state_ignores_non_finite_lease_time(self) -> None:
        registry = validate_registry()
        workers = registry["architecture"]["workers"]
        worker_id = workers["roles"]["coder"][0]
        state = self._write(
            "worker_state_non_finite.json",
            {
                "leases": {
                    "task": {
                        "worker_id": worker_id,
                        "role": "coder",
                        "task_id": "task",
                        "leased_at": float("nan"),
                        "standby": False,
                    }
                }
            },
        )

        router = WorkerRouter(
            health_file=self._worker_health(),
            state_file=state,
        )
        self.assertNotIn("task", router.leases)


class RouterExhaustionContractTests(unittest.TestCase):
    def test_leader_unavailable_type_is_explicit(self) -> None:
        self.assertTrue(issubclass(LeaderUnavailable, Exception))

    def test_worker_configuration_error_is_explicit(self) -> None:
        self.assertTrue(issubclass(ConfigurationError, Exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
