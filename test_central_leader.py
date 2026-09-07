from __future__ import annotations

import unittest

from central_leader import (
    CentralLeader,
    CentralLeaderError,
    LeaderPlanningSafetyStop,
    LeaderRequest,
)
from leader_router import LeaderLease


class FakeRouter:
    def __init__(self) -> None:
        self.leases = {}
        self.failures = []
        self.released = []

    def acquire(self, task_id: str) -> LeaderLease:
        lease = LeaderLease(
            provider="openrouter",
            account_id="OR-27",
            model="nvidia/test-model",
            tier="ULTRA",
            task_id=task_id,
            leased_at=1.0,
        )
        self.leases[task_id] = lease
        return lease

    def release(self, task_id: str) -> LeaderLease:
        lease = self.leases.pop(task_id)
        self.released.append(task_id)
        return lease

    def fail_current_leader(self, task_id: str, reason: str) -> LeaderLease:
        lease = self.leases.pop(task_id)
        self.failures.append((task_id, reason))
        return lease


class CentralLeaderTests(unittest.TestCase):
    def _context(self, state: str = "CONTINUE", *, autonomous_start_allowed: bool = True) -> dict:
        return {
            "schema_version": 1,
            "authority": {
                "execution_authorized": False,
                "mutation_allowed": False,
                "source_contents_included": False,
            },
            "project": {
                "state": state,
                "confidence": 0.9,
                "autonomous_start_allowed": autonomous_start_allowed,
            },
            "requirements": [],
        }

    def test_prepare_uses_router_identity_without_hardcoded_account_limit(self) -> None:
        router = FakeRouter()
        leader = CentralLeader(router=router)

        request = leader.prepare("task-1", self._context())

        self.assertIsInstance(request, LeaderRequest)
        self.assertEqual(request.account_id, "OR-27")
        self.assertEqual(request.provider, "openrouter")
        self.assertEqual(request.model, "nvidia/test-model")
        self.assertEqual(request.task_id, "task-1")

    def test_planning_output_remains_untrusted_and_does_not_authorize_execution(self) -> None:
        router = FakeRouter()
        leader = CentralLeader(
            router=router,
            transport=lambda request: {
                "proposal": "change app.py",
                "authority": {"execution_authorized": True},
            },
        )

        response = leader.plan("task-2", self._context())

        self.assertEqual(response.payload["proposal"], "change app.py")
        self.assertTrue(response.payload["authority"]["execution_authorized"])
        self.assertEqual(response.account_id, "OR-27")
        self.assertIn("task-2", router.leases)

    def test_runtime_transport_failure_is_reported_to_router(self) -> None:
        router = FakeRouter()

        def failing_transport(_: LeaderRequest) -> object:
            raise TimeoutError("provider timeout")

        leader = CentralLeader(router=router, transport=failing_transport)

        with self.assertRaises(TimeoutError):
            leader.plan("task-3", self._context())

        self.assertEqual(router.failures, [("task-3", "TimeoutError")])
        self.assertNotIn("task-3", router.leases)

    def test_unknown_and_conflict_states_are_safety_stops(self) -> None:
        leader = CentralLeader(router=FakeRouter(), transport=lambda _: None)

        for state in ("UNKNOWN", "CONFLICT"):
            with self.subTest(state=state):
                with self.assertRaises(LeaderPlanningSafetyStop):
                    leader.prepare(f"stop-{state}", self._context(state))

    def test_autonomous_start_must_be_explicitly_allowed(self) -> None:
        leader = CentralLeader(router=FakeRouter(), transport=lambda _: None)

        for value in (False, None):
            context = self._context(autonomous_start_allowed=True)
            context["project"].pop("autonomous_start_allowed", None) if value is None else context["project"].update(
                {"autonomous_start_allowed": value}
            )
            with self.subTest(value=value):
                with self.assertRaises(LeaderPlanningSafetyStop):
                    leader.prepare("blocked-autonomous-start", context)

    def test_context_cannot_grant_execution_or_mutation_authority(self) -> None:
        leader = CentralLeader(router=FakeRouter())

        cases = [
            {"execution_authorized": True, "mutation_allowed": False},
            {"execution_authorized": False, "mutation_allowed": True},
            {"execution_authorized": False, "mutation_allowed": False, "source_contents_included": True},
        ]
        for authority in cases:
            context = self._context()
            context["authority"].update(authority)
            with self.subTest(authority=authority):
                with self.assertRaises(CentralLeaderError):
                    leader.prepare("unsafe", context)

    def test_network_transport_is_not_configured_by_default(self) -> None:
        leader = CentralLeader(router=FakeRouter())
        with self.assertRaises(CentralLeaderError):
            leader.plan("task-4", self._context())


if __name__ == "__main__":
    unittest.main(verbosity=2)
