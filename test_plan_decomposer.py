from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from plan_decomposer import PlanDecomposer, PlanDecompositionError, decompose_plan


class PlanDecomposerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.roles = ("coder", "debugger", "tester", "reviewer")
        self.decomposer = PlanDecomposer(allowed_roles=self.roles)
        self.output = {
            "plan": {
                "goal": "Implement the requested behavior",
                "tasks": [
                    {
                        "task_id": "TASK-1",
                        "role": "coder",
                        "objective": "Implement the core behavior",
                        "depends_on": [],
                        "acceptance_criteria": ["Unit tests cover the behavior"],
                        "priority": 90,
                    },
                    {
                        "task_id": "TASK-2",
                        "role": "tester",
                        "objective": "Validate the implementation",
                        "depends_on": ["TASK-1"],
                        "acceptance_criteria": ["Relevant tests pass"],
                        "priority": 80,
                    },
                ],
            }
        }

    def test_normalizes_valid_plan_and_preserves_planning_only_authority(self) -> None:
        result = self.decomposer.decompose(self.output)

        self.assertEqual(result["plan_kind"], "validated_task_plan")
        self.assertEqual(result["validation"]["task_count"], 2)
        self.assertTrue(result["validation"]["dag_valid"])
        self.assertFalse(result["authority"]["execution_authorized"])
        self.assertFalse(result["authority"]["mutation_allowed"])
        self.assertFalse(result["authority"]["worker_assignment_authorized"])
        self.assertFalse(result["authority"]["model_output_trusted"])

    def test_accepts_json_object_string(self) -> None:
        result = decompose_plan(json.dumps(self.output), allowed_roles=self.roles)
        self.assertEqual([task["task_id"] for task in result["tasks"]], ["TASK-1", "TASK-2"])

    def test_rejects_unconfigured_role(self) -> None:
        output = json.loads(json.dumps(self.output))
        output["plan"]["tasks"][0]["role"] = "architect"

        with self.assertRaisesRegex(PlanDecompositionError, "unconfigured worker role"):
            self.decomposer.decompose(output)

    def test_rejects_missing_dependency(self) -> None:
        output = json.loads(json.dumps(self.output))
        output["plan"]["tasks"][1]["depends_on"] = ["TASK-999"]

        with self.assertRaisesRegex(PlanDecompositionError, "unknown tasks"):
            self.decomposer.decompose(output)

    def test_rejects_dependency_cycle(self) -> None:
        output = json.loads(json.dumps(self.output))
        output["plan"]["tasks"][0]["depends_on"] = ["TASK-2"]

        with self.assertRaisesRegex(PlanDecompositionError, "cycle"):
            self.decomposer.decompose(output)

    def test_rejects_duplicate_task_ids(self) -> None:
        output = json.loads(json.dumps(self.output))
        output["plan"]["tasks"][1]["task_id"] = "TASK-1"

        with self.assertRaisesRegex(PlanDecompositionError, "Duplicate task_id"):
            self.decomposer.decompose(output)

    def test_rejects_empty_acceptance_criteria(self) -> None:
        output = json.loads(json.dumps(self.output))
        output["plan"]["tasks"][0]["acceptance_criteria"] = []

        with self.assertRaisesRegex(PlanDecompositionError, "acceptance criteria"):
            self.decomposer.decompose(output)

    def test_rejects_unsafe_context_authority(self) -> None:
        context = {
            "authority": {
                "execution_authorized": True,
                "mutation_allowed": False,
            }
        }
        with self.assertRaisesRegex(PlanDecompositionError, "cannot authorize execution"):
            self.decomposer.decompose(self.output, context=context)

    def test_task_limit_is_enforced(self) -> None:
        output = json.loads(json.dumps(self.output))
        decomposer = PlanDecomposer(max_tasks=1, allowed_roles=self.roles)

        with self.assertRaisesRegex(PlanDecompositionError, "max_tasks"):
            decomposer.decompose(output)

    def test_registry_roles_are_nondestructively_read(self) -> None:
        with patch("plan_decomposer.validate_registry", return_value={
            "architecture": {
                "workers": {
                    "roles": {
                        "new-role": ["GROQ-99"],
                        "empty-role": [],
                    }
                }
            }
        }):
            decomposer = PlanDecomposer()
            self.assertEqual(decomposer.allowed_roles, {"new-role"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
