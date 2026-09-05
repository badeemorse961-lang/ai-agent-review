from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from execution_authorization import (
    ExecutionAuthorizationBoundary,
    ExecutionAuthorizationSafetyStop,
)
from execution_gate import FileChange
from independent_validation import ValidationVerdict


class ExecutionAuthorizationTests(unittest.TestCase):
    def _workspace(self) -> Path:
        self.temp_dir = tempfile.TemporaryDirectory()
        return Path(self.temp_dir.name).resolve()

    def tearDown(self) -> None:
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

    @staticmethod
    def _verdict(targets=None, passed=True) -> ValidationVerdict:
        return ValidationVerdict(
            task_id="TASK-1",
            worker_id="GROQ-01",
            passed=passed,
            reasons=(),
            evidence={
                "passed": passed,
                "changed_targets": targets or ["target.txt"],
            },
        )

    @staticmethod
    def _checkpoint() -> dict:
        return {"checkpoint_id": "CP-1", "isolated": True}

    def _change(self, path: str = "target.txt") -> FileChange:
        return FileChange(path=path, old_text="before\n", new_text="after\n")

    def test_authorization_requires_passed_independent_validation(self) -> None:
        root = self._workspace()
        boundary = ExecutionAuthorizationBoundary(root)
        with self.assertRaises(ExecutionAuthorizationSafetyStop):
            boundary.authorize(
                self._verdict(passed=False),
                checkpoint=self._checkpoint(),
                changes=[self._change()],
            )

    def test_authorization_requires_isolated_checkpoint(self) -> None:
        root = self._workspace()
        boundary = ExecutionAuthorizationBoundary(root)
        with self.assertRaises(ExecutionAuthorizationSafetyStop):
            boundary.authorize(
                self._verdict(),
                checkpoint={"checkpoint_id": "CP-1", "isolated": False},
                changes=[self._change()],
            )

    def test_authorization_is_internal_and_does_not_require_human_approval(self) -> None:
        root = self._workspace()
        boundary = ExecutionAuthorizationBoundary(root)
        record = boundary.authorize(
            self._verdict(),
            checkpoint=self._checkpoint(),
            changes=[self._change()],
        )
        self.assertTrue(record.authorized)
        self.assertIn("independent_validation_passed", record.basis)

    def test_targets_must_match_validation_evidence_exactly(self) -> None:
        root = self._workspace()
        boundary = ExecutionAuthorizationBoundary(root)
        with self.assertRaises(ExecutionAuthorizationSafetyStop):
            boundary.authorize(
                self._verdict(targets=["other.txt"]),
                checkpoint=self._checkpoint(),
                changes=[self._change()],
            )

    def test_authorization_returns_auditable_record(self) -> None:
        root = self._workspace()
        boundary = ExecutionAuthorizationBoundary(root)
        record = boundary.authorize(
            self._verdict(),
            checkpoint=self._checkpoint(),
            changes=[self._change()],
        )
        self.assertEqual(record.task_id, "TASK-1")
        self.assertEqual(record.worker_id, "GROQ-01")
        self.assertTrue(record.authorized)
        self.assertEqual(record.changed_targets, ("target.txt",))
        self.assertEqual(record.to_dict()["schema_version"], 2)

    def test_apply_delegates_only_after_internal_authorization(self) -> None:
        root = self._workspace()
        boundary = ExecutionAuthorizationBoundary(root)
        target = root / "target.txt"
        target.write_text("before\n", encoding="utf-8")
        boundary.gate.execute = Mock(return_value={"status": "APPROVED"})

        result = boundary.apply(
            self._verdict(),
            checkpoint=self._checkpoint(),
            changes=[self._change()],
        )

        boundary.gate.execute.assert_called_once()
        self.assertEqual(result["authorization"]["authorized"], True)
        self.assertEqual(result["transaction"]["status"], "APPROVED")
        self.assertEqual(target.read_text(encoding="utf-8"), "before\n")

    def test_unsafe_absolute_evidence_target_is_rejected(self) -> None:
        root = self._workspace()
        boundary = ExecutionAuthorizationBoundary(root)
        with self.assertRaises(ExecutionAuthorizationSafetyStop):
            boundary.authorize(
                self._verdict(targets=[str(root / "target.txt")]),
                checkpoint=self._checkpoint(),
                changes=[self._change()],
            )

    def test_unsafe_traversal_change_is_rejected(self) -> None:
        root = self._workspace()
        boundary = ExecutionAuthorizationBoundary(root)
        with self.assertRaises(ExecutionAuthorizationSafetyStop):
            boundary.authorize(
                self._verdict(targets=["../target.txt"]),
                checkpoint=self._checkpoint(),
                changes=[self._change("../target.txt")],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
