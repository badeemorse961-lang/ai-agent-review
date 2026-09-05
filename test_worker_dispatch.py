from __future__ import annotations

import unittest
from unittest.mock import Mock

from worker_dispatch import WorkerDispatcher, WorkerDispatchSafetyStop
from worker_router import WorkerLease


class WorkerDispatchTests(unittest.TestCase):
    def _router(self) -> Mock:
        router = Mock()
        router.worker_pools = {
            "coder": ["GROQ-01", "GROQ-02"],
            "tester": ["GROQ-08"],
            "standby": ["GROQ-15"],
        }
        router.acquire.side_effect = [
            WorkerLease("GROQ-01", "coder", "TASK-1", 1.0, False),
            WorkerLease("GROQ-08", "tester", "TASK-2", 2.0, False),
        ]
        return router

    def _plan(self) -> dict:
        return {
            "schema_version": 1,
            "plan_kind": "validated_task_plan",
            "goal": "Implement the change",
            "tasks": [
                {
                    "task_id": "TASK-2",
                    "role": "tester",
                    "objective": "Add tests",
                    "depends_on": ["TASK-1"],
                    "acceptance_criteria": ["Tests pass"],
                    "priority": 50,
                },
                {
                    "task_id": "TASK-1",
                    "role": "coder",
                    "objective": "Implement code",
                    "depends_on": [],
                    "acceptance_criteria": ["Code works"],
                    "priority": 80,
                },
            ],
            "authority": {
                "execution_authorized": False,
                "mutation_allowed": False,
                "worker_assignment_authorized": False,
                "model_output_trusted": False,
            },
            "validation": {"dag_valid": True, "roles_valid": True},
        }

    def test_dispatch_follows_dependency_order(self) -> None:
        router = self._router()
        assignments = WorkerDispatcher(router).assign_plan(self._plan())

        self.assertEqual([item.task_id for item in assignments], ["TASK-1", "TASK-2"])
        self.assertEqual(router.acquire.call_args_list[0].args, ("coder", "TASK-1"))
        self.assertEqual(router.acquire.call_args_list[1].args, ("tester", "TASK-2"))

    def test_dispatch_rejects_execution_authority(self) -> None:
        plan = self._plan()
        plan["authority"]["execution_authorized"] = True
        with self.assertRaises(WorkerDispatchSafetyStop):
            WorkerDispatcher(self._router()).assign_plan(plan)

    def test_dispatch_rejects_invalid_plan(self) -> None:
        plan = self._plan()
        plan["validation"]["dag_valid"] = False
        with self.assertRaises(WorkerDispatchSafetyStop):
            WorkerDispatcher(self._router()).assign_plan(plan)

    def test_dispatch_rolls_back_previous_leases_on_assignment_failure(self) -> None:
        router = self._router()
        router.acquire.side_effect = [
            WorkerLease("GROQ-01", "coder", "TASK-1", 1.0, False),
            RuntimeError("worker unavailable"),
        ]

        with self.assertRaises(RuntimeError):
            WorkerDispatcher(router).assign_plan(self._plan())

        router.release.assert_called_once_with("TASK-1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
