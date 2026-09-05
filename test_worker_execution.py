from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from worker_execution import WorkerExecutionBoundary, WorkerExecutionSafetyStop


class WorkerExecutionBoundaryTests(unittest.TestCase):
    def _workspace(self) -> Path:
        self.temp_dir = tempfile.TemporaryDirectory()
        return Path(self.temp_dir.name)

    def tearDown(self) -> None:
        if hasattr(self, "temp_dir"):
            self.temp_dir.cleanup()

    def _assignment(self, *, standby: bool = False) -> dict:
        return {
            "task_id": "TASK-1",
            "role": "coder",
            "worker_id": "GROQ-01",
            "standby": standby,
        }

    def _task(self) -> dict:
        return {
            "task_id": "TASK-1",
            "role": "coder",
            "acceptance_criteria": ["Command succeeds"],
            "authority": {
                "execution_authorized": False,
                "mutation_allowed": False,
            },
        }

    def test_execution_requires_checkpoint(self) -> None:
        root = self._workspace()
        boundary = WorkerExecutionBoundary(root)
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                self._task(),
                command=[sys.executable, "-c", "print('ok')"],
            )

    def test_allowed_command_executes_in_workspace(self) -> None:
        root = self._workspace()
        seen = []

        def checkpoint(request):
            seen.append(request.workspace_root)
            return {"checkpoint_id": "CP-1"}

        boundary = WorkerExecutionBoundary(root, checkpoint=checkpoint, allowed_commands=[sys.executable])
        result = boundary.execute(
            self._assignment(),
            self._task(),
            command=[sys.executable, "-c", "print('ok')"],
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(result.stdout.strip(), "ok")
        self.assertEqual(seen, [str(root.resolve())])
        self.assertEqual(result.checkpoint, {"checkpoint_id": "CP-1"})

    def test_non_allowlisted_command_is_rejected(self) -> None:
        root = self._workspace()
        boundary = WorkerExecutionBoundary(
            root,
            checkpoint=lambda request: "CP-1",
            allowed_commands=["python"],
        )
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                self._task(),
                command=["powershell", "-Command", "Write-Output ok"],
            )

    def test_path_escape_is_rejected(self) -> None:
        root = self._workspace()
        boundary = WorkerExecutionBoundary(
            root,
            checkpoint=lambda request: "CP-1",
            allowed_commands=[sys.executable],
        )
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                self._task(),
                command=[sys.executable, "-c", "print('ok')"],
                targets=["../outside.txt"],
            )

    def test_standby_assignment_cannot_execute_directly(self) -> None:
        root = self._workspace()
        boundary = WorkerExecutionBoundary(
            root,
            checkpoint=lambda request: "CP-1",
            allowed_commands=[sys.executable],
        )
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(standby=True),
                self._task(),
                command=[sys.executable, "-c", "print('ok')"],
            )

    def test_timeout_is_safe_stop(self) -> None:
        root = self._workspace()
        boundary = WorkerExecutionBoundary(
            root,
            checkpoint=lambda request: "CP-1",
            allowed_commands=[sys.executable],
            timeout_seconds=0.05,
        )
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                self._task(),
                command=[sys.executable, "-c", "import time; time.sleep(2)"],
            )

    def test_output_is_bounded(self) -> None:
        root = self._workspace()
        boundary = WorkerExecutionBoundary(
            root,
            checkpoint=lambda request: "CP-1",
            allowed_commands=[sys.executable],
            max_output_chars=256,
        )
        result = boundary.execute(
            self._assignment(),
            self._task(),
            command=[sys.executable, "-c", "print('x' * 1000)"],
        )
        self.assertTrue(result.truncated)
        self.assertEqual(len(result.stdout), 256)

    def test_task_and_assignment_identity_must_match(self) -> None:
        root = self._workspace()
        boundary = WorkerExecutionBoundary(
            root,
            checkpoint=lambda request: "CP-1",
            allowed_commands=[sys.executable],
        )
        task = self._task()
        task["task_id"] = "TASK-2"
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                task,
                command=[sys.executable, "-c", "print('ok')"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
