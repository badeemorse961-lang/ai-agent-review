from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from independent_validation import (
    IndependentValidationSafetyStop,
    IndependentValidator,
)
from worker_execution import ExecutionRequest, ExecutionResult


class IndependentValidationTests(unittest.TestCase):
    def _workspace(self) -> Path:
        self.temp_dir = tempfile.TemporaryDirectory()
        return Path(self.temp_dir.name).resolve()

    def tearDown(self) -> None:
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

    def _request(self, root: Path) -> ExecutionRequest:
        return ExecutionRequest(
            task_id="TASK-1",
            role="coder",
            worker_id="GROQ-01",
            workspace_root=str(root),
            command=("python", "worker.py"),
            targets=("worker.py",),
            timeout_seconds=120.0,
        )

    @staticmethod
    def _task() -> dict:
        return {
            "task_id": "TASK-1",
            "role": "coder",
            "acceptance_criteria": ["Independent checks pass"],
        }

    @staticmethod
    def _result(**overrides) -> ExecutionResult:
        values = {
            "returncode": 0,
            "stdout": "ok",
            "stderr": "",
            "timed_out": False,
            "truncated": False,
            "checkpoint": {"checkpoint_id": "CP-1", "isolated": True},
        }
        values.update(overrides)
        return ExecutionResult(**values)

    @staticmethod
    def _hook(request, task, result):
        return {"passed": True, "checks": ["tests", "verification"]}

    def test_requires_independent_pass_attestation(self) -> None:
        root = self._workspace()
        validator = IndependentValidator(
            root,
            validation_hook=lambda request, task, result: {"passed": False, "reason": "tests failed"},
        )
        with self.assertRaises(IndependentValidationSafetyStop):
            validator.validate(self._request(root), self._task(), self._result())

    def test_worker_success_alone_is_not_enough(self) -> None:
        root = self._workspace()
        called = []

        def hook(request, task, result):
            called.append(result.succeeded)
            return {"passed": True, "checks": ["independent-check"]}

        validator = IndependentValidator(root, validation_hook=hook)
        verdict = validator.validate(self._request(root), self._task(), self._result())
        self.assertTrue(verdict.passed)
        self.assertEqual(called, [True])

    def test_task_identity_must_match(self) -> None:
        root = self._workspace()
        task = self._task()
        task["task_id"] = "TASK-2"
        validator = IndependentValidator(root, validation_hook=self._hook)
        with self.assertRaises(IndependentValidationSafetyStop):
            validator.validate(self._request(root), task, self._result())

    def test_workspace_must_match(self) -> None:
        root = self._workspace()
        other = root.parent / (root.name + "-other")
        other.mkdir()
        self.addCleanup(other.rmdir)
        request = self._request(other)
        validator = IndependentValidator(root, validation_hook=self._hook)
        with self.assertRaises(IndependentValidationSafetyStop):
            validator.validate(request, self._task(), self._result())

    def test_nonzero_execution_cannot_be_approved(self) -> None:
        root = self._workspace()
        validator = IndependentValidator(root, validation_hook=self._hook)
        with self.assertRaises(IndependentValidationSafetyStop):
            validator.validate(
                self._request(root),
                self._task(),
                self._result(returncode=1),
            )

    def test_truncated_output_cannot_be_approved(self) -> None:
        root = self._workspace()
        validator = IndependentValidator(root, validation_hook=self._hook)
        with self.assertRaises(IndependentValidationSafetyStop):
            validator.validate(
                self._request(root),
                self._task(),
                self._result(truncated=True),
            )

    def test_changed_target_must_stay_inside_workspace(self) -> None:
        root = self._workspace()
        validator = IndependentValidator(root, validation_hook=self._hook)
        with self.assertRaises(IndependentValidationSafetyStop):
            validator.validate(
                self._request(root),
                self._task(),
                self._result(),
                changed_targets=["../outside.py"],
            )

    def test_isolated_checkpoint_is_required(self) -> None:
        root = self._workspace()
        validator = IndependentValidator(root, validation_hook=self._hook)
        with self.assertRaises(IndependentValidationSafetyStop):
            validator.validate(
                self._request(root),
                self._task(),
                self._result(checkpoint={"checkpoint_id": "CP-1", "isolated": False}),
            )

    def test_successful_validation_returns_auditable_verdict(self) -> None:
        root = self._workspace()
        validator = IndependentValidator(root, validation_hook=self._hook)
        verdict = validator.validate(
            self._request(root),
            self._task(),
            self._result(),
            changed_targets=["worker.py", "src/module.py"],
        )
        self.assertEqual(verdict.task_id, "TASK-1")
        self.assertEqual(verdict.worker_id, "GROQ-01")
        self.assertTrue(verdict.passed)
        self.assertEqual(verdict.evidence["changed_targets"], ["worker.py", "src/module.py"])
        self.assertEqual(verdict.to_dict()["schema_version"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
