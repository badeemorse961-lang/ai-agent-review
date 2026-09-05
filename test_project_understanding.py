from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from current_state_analyzer import CurrentStateAnalyzer
from gap_compliance import GapComplianceAnalyzer
from project_scanner import ProjectScanner
from project_state_classifier import ProjectStateClassifier
from project_understanding_pipeline import ProjectUnderstandingPipeline
from specification_analyzer import SpecificationAnalyzer


class ProjectUnderstandingTests(unittest.TestCase):
    def _workspace(self) -> Path:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        (root / "app.py").write_text(
            """def add(a, b):\n    return a + b\n\n\ndef multiply(a, b):\n    return a * b\n""",
            encoding="utf-8",
        )
        (root / "test_app.py").write_text(
            """from app import add, multiply\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\ndef test_multiply():\n    assert multiply(2, 3) == 6\n""",
            encoding="utf-8",
        )
        (root / "TASK.md").write_text(
            """# المهمة\n\nالمتطلبات:\n- add(a, b) يجب أن يرجع a + b\n- multiply(a, b) يجب أن يرجع a * b\n- divide(a, 0) يجب أن يرفع ZeroDivisionError\n- لا تعيد كتابة المشروع\n""",
            encoding="utf-8",
        )
        return root

    def tearDown(self) -> None:
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

    def test_specification_analyzer_extracts_stable_requirement_records(self) -> None:
        root = self._workspace()
        result = SpecificationAnalyzer(root).analyze()

        self.assertEqual(result["requirement_count"], 4)
        self.assertEqual(
            [item["source"] for item in result["requirements"]],
            ["TASK.md"] * 4,
        )
        self.assertTrue(all(item["requirement_id"].startswith("REQ-") for item in result["requirements"]))
        self.assertEqual(result["requirements"][0]["strength"], "mandatory")

    def test_current_state_analyzer_separates_implementation_and_test_evidence(self) -> None:
        root = self._workspace()
        manifest = ProjectScanner(root, output_file=root / "manifest.json").scan()
        specification = SpecificationAnalyzer(root).analyze()
        result = CurrentStateAnalyzer(root).analyze(specification, manifest)

        self.assertEqual(len(result["requirements"]), 4)
        add_evidence = result["requirements"][0]
        self.assertTrue(add_evidence["implementation_evidence"])
        self.assertTrue(add_evidence["test_evidence"])
        self.assertEqual(add_evidence["evidence_level"], "IMPLEMENTATION_AND_TEST_EVIDENCE")

    def test_gap_compliance_does_not_claim_runtime_compliance_from_static_matches(self) -> None:
        root = self._workspace()
        manifest = ProjectScanner(root, output_file=root / "manifest.json").scan()
        specification = SpecificationAnalyzer(root).analyze()
        current = CurrentStateAnalyzer(root).analyze(specification, manifest)
        result = GapComplianceAnalyzer().analyze(specification, current)

        self.assertEqual(result["summary"]["verified"], 0)
        self.assertGreaterEqual(result["summary"]["implemented_unverified"], 2)
        self.assertFalse(result["summary"]["autonomous_compliance_proven"])

    def test_execution_evidence_can_prove_a_requirement(self) -> None:
        root = self._workspace()
        specification = SpecificationAnalyzer(root).analyze()
        manifest = ProjectScanner(root, output_file=root / "manifest.json").scan()
        target = specification["requirements"][0]["requirement_id"]
        current = CurrentStateAnalyzer(root).analyze(
            specification,
            manifest,
            execution_evidence={target: {"passed": True}},
        )
        result = GapComplianceAnalyzer().analyze(specification, current)

        self.assertEqual(result["requirements"][0]["status"], "VERIFIED")
        self.assertEqual(result["summary"]["verified"], 1)

    def test_failed_execution_evidence_becomes_gap(self) -> None:
        root = self._workspace()
        specification = SpecificationAnalyzer(root).analyze()
        manifest = ProjectScanner(root, output_file=root / "manifest.json").scan()
        target = specification["requirements"][0]["requirement_id"]
        current = CurrentStateAnalyzer(root).analyze(
            specification,
            manifest,
            execution_evidence={target: {"passed": False, "reason": "assertion failed"}},
        )
        result = GapComplianceAnalyzer().analyze(specification, current)

        self.assertEqual(result["requirements"][0]["status"], "GAP")
        self.assertEqual(result["summary"]["gaps"], 1)

    def test_unknown_requirement_remains_unknown(self) -> None:
        root = self._workspace()
        (root / "TASK.md").write_text(
            "# Requirements\n\n- A unique subsystem must exist and emit a signed event.\n",
            encoding="utf-8",
        )
        specification = SpecificationAnalyzer(root).analyze()
        manifest = ProjectScanner(root, output_file=root / "manifest.json").scan()
        current = CurrentStateAnalyzer(root).analyze(specification, manifest)
        result = GapComplianceAnalyzer().analyze(specification, current)

        self.assertEqual(result["requirements"][0]["status"], "UNKNOWN")
        self.assertEqual(result["summary"]["unknown"], 1)

    def test_pipeline_produces_connected_evidence_bundle(self) -> None:
        root = self._workspace()
        bundle = ProjectUnderstandingPipeline(root).analyze()
        summary = ProjectUnderstandingPipeline.summarize(bundle)

        self.assertIn(bundle["classification"]["state"], {"BUILD", "CONTINUE", "MAINTAIN", "UNKNOWN", "REPAIR", "CONFLICT"})
        self.assertEqual(summary["requirement_count"], 4)
        self.assertIn("gap_compliance", bundle)
        self.assertIn("current_state", bundle)
        self.assertIn("context", bundle)
        self.assertEqual(bundle["context"]["authority"]["execution_authorized"], False)
        self.assertEqual(summary["context_execution_authorized"], False)
        self.assertEqual(bundle["schema_version"], 1)

    def test_pipeline_does_not_authorize_execution_from_static_evidence(self) -> None:
        root = self._workspace()
        bundle = ProjectUnderstandingPipeline(root).analyze()

        self.assertFalse(bundle["gap_compliance"]["summary"]["autonomous_compliance_proven"])
        self.assertIn("not an execution authorization", bundle["authority_note"])
        self.assertFalse(bundle["context"]["authority"]["execution_authorized"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
