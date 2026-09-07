from __future__ import annotations

import unittest

from context_builder import ContextBuilder, build_context


class ContextBuilderTests(unittest.TestCase):
    def _bundle(self) -> dict:
        return {
            "classification": {
                "state": "CONTINUE",
                "confidence": 0.91,
                "rationale": "Implementation exists and required work remains.",
                "unresolved_requirements": 1,
                "autonomous_start_allowed": True,
            },
            "specification": {
                "requirements": [
                    {
                        "requirement_id": "REQ-1",
                        "source": "TASK.md",
                        "line": 3,
                        "text": "add(a, b) must return a + b",
                        "kind": "behavior",
                        "strength": "mandatory",
                    },
                    {
                        "requirement_id": "REQ-2",
                        "source": "TASK.md",
                        "line": 4,
                        "text": "divide(a, 0) must raise ZeroDivisionError",
                        "kind": "behavior",
                        "strength": "mandatory",
                    },
                ]
            },
            "current_state": {
                "requirements": [
                    {
                        "requirement_id": "REQ-1",
                        "implementation_evidence": [{"path": "calculator.py"}],
                        "test_evidence": [{"path": "test_calculator.py"}],
                        "execution_evidence": None,
                    },
                    {
                        "requirement_id": "REQ-2",
                        "implementation_evidence": [],
                        "test_evidence": [{"path": "test_calculator.py"}],
                        "execution_evidence": None,
                    },
                ]
            },
            "gap_compliance": {
                "summary": {
                    "requirement_count": 2,
                    "verified": 0,
                    "implemented_unverified": 1,
                    "tested_unimplemented": 1,
                    "gaps": 0,
                    "unknown": 0,
                    "autonomous_compliance_proven": False,
                },
                "requirements": [
                    {"requirement_id": "REQ-1", "status": "IMPLEMENTED_UNVERIFIED"},
                    {"requirement_id": "REQ-2", "status": "TESTED_UNIMPLEMENTED"},
                ],
            },
            "authority_note": "not an execution authorization",
        }

    def test_context_is_deterministic_and_evidence_only(self) -> None:
        builder = ContextBuilder()
        first = builder.build(self._bundle())
        second = builder.build(self._bundle())

        self.assertEqual(first, second)
        self.assertFalse(first["authority"]["execution_authorized"])
        self.assertFalse(first["authority"]["mutation_allowed"])
        self.assertFalse(first["authority"]["source_contents_included"])
        self.assertTrue(first["requirements"])
        self.assertEqual(first["requirements"][0]["requirement_id"], "REQ-2")

    def test_gaps_are_prioritized_before_verified_requirements(self) -> None:
        bundle = self._bundle()
        bundle["specification"]["requirements"].append(
            {
                "requirement_id": "REQ-3",
                "source": "TASK.md",
                "line": 5,
                "text": "A stable API must exist",
                "kind": "behavior",
                "strength": "mandatory",
            }
        )
        bundle["current_state"]["requirements"].append(
            {
                "requirement_id": "REQ-3",
                "implementation_evidence": [{"path": "api.py"}],
                "test_evidence": [],
                "execution_evidence": {"passed": False, "reason": "missing endpoint"},
            }
        )
        bundle["gap_compliance"]["requirements"].append(
            {"requirement_id": "REQ-3", "status": "GAP"}
        )

        context = ContextBuilder().build(bundle)
        self.assertEqual(context["requirements"][0]["requirement_id"], "REQ-3")
        self.assertEqual(context["requirements"][0]["status"], "GAP")

    def test_static_evidence_does_not_become_runtime_proof(self) -> None:
        context = ContextBuilder().build(self._bundle())
        req1 = next(item for item in context["requirements"] if item["requirement_id"] == "REQ-1")

        self.assertEqual(req1["status"], "IMPLEMENTED_UNVERIFIED")
        self.assertFalse(req1["execution_evidence_present"])

    def test_explicit_execution_evidence_is_carried_without_authorizing_execution(self) -> None:
        bundle = self._bundle()
        bundle["current_state"]["requirements"][0]["execution_evidence"] = {"passed": True}
        bundle["gap_compliance"]["requirements"][0]["status"] = "VERIFIED"
        bundle["gap_compliance"]["summary"]["verified"] = 1

        context = build_context(bundle)
        req1 = next(item for item in context["requirements"] if item["requirement_id"] == "REQ-1")

        self.assertTrue(req1["execution_evidence_present"])
        self.assertEqual(req1["status"], "VERIFIED")
        self.assertFalse(context["authority"]["execution_authorized"])

    def test_budget_is_bounded_and_reports_truncation(self) -> None:
        bundle = self._bundle()
        for number in range(3, 30):
            requirement_id = f"REQ-{number}"
            bundle["specification"]["requirements"].append(
                {
                    "requirement_id": requirement_id,
                    "source": "TASK.md",
                    "line": number,
                    "text": f"Requirement {number} must be satisfied by the implementation",
                    "kind": "behavior",
                    "strength": "mandatory",
                }
            )
            bundle["current_state"]["requirements"].append(
                {
                    "requirement_id": requirement_id,
                    "implementation_evidence": [{"path": f"module_{number}.py"}],
                    "test_evidence": [],
                    "execution_evidence": None,
                }
            )
            bundle["gap_compliance"]["requirements"].append(
                {"requirement_id": requirement_id, "status": "IMPLEMENTED_UNVERIFIED"}
            )

        context = ContextBuilder(max_chars=1200).build(bundle)
        self.assertLessEqual(len(ContextBuilder._serialize(context)), 1200)
        self.assertTrue(context["budget"]["truncated"])
        self.assertGreater(context["budget"]["omitted_requirements"], 0)

    def test_invalid_budget_parameters_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ContextBuilder(max_chars=100)
        with self.assertRaises(ValueError):
            ContextBuilder(max_requirements=0)

    def test_prose_terms_are_not_treated_as_secret_leaks(self) -> None:
        bundle = self._bundle()
        bundle["specification"]["requirements"][0][
            "text"
        ] = "The application must document its secret handling, token lifecycle, and credential policy."

        context = ContextBuilder().build(bundle)

        self.assertIn("secret handling", context["requirements"][0]["text"])
        self.assertIn("token lifecycle", context["requirements"][0]["text"])
        self.assertIn("credential policy", context["requirements"][0]["text"])

    def test_sensitive_keys_are_still_redacted_and_untrusted_secret_values_rejected(self) -> None:
        bundle = self._bundle()
        bundle["specification"]["requirements"][0]["api_key"] = "sk-test-not-a-real-key-but-sensitive"

        context = ContextBuilder().build(bundle)
        self.assertEqual(context["requirements"][0].get("api_key"), None)

        leaked = self._bundle()
        leaked["specification"]["requirements"][0]["text"] = "Bearer abcdefghijklmnopqrstuvwxyz123456"
        with self.assertRaises(ValueError):
            ContextBuilder().build(leaked)


if __name__ == "__main__":
    unittest.main(verbosity=2)