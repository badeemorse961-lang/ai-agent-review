from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from process_sandbox import ProcessSandbox, ProcessSandboxSafetyStop
from sandbox_policy import WorkspaceResourcePolicy
from terminal_executor import TerminalExecutor
from terminal_policy import TerminalCommandPolicy, TerminalPolicy
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

    @staticmethod
    def _checkpoint(request):
        return {"checkpoint_id": "CP-1", "isolated": True}

    def _script(self, root: Path, name: str, body: str) -> Path:
        script = root / name
        script.write_text(body, encoding="utf-8")
        return script

    def _sandbox(self, root: Path, *, timeout: float = 3.0) -> ProcessSandbox:
        executable = Path(sys.executable).resolve()
        policy = WorkspaceResourcePolicy(
            root,
            allowed_tool_paths=[executable],
        )
        return ProcessSandbox(policy, timeout_seconds=timeout)

    def _boundary(self, root: Path, *, timeout: float = 3.0) -> WorkerExecutionBoundary:
        return WorkerExecutionBoundary(
            root,
            checkpoint=self._checkpoint,
            allowed_commands=[sys.executable],
            process_sandbox=self._sandbox(root, timeout=timeout),
            timeout_seconds=timeout,
        )

    def test_execution_requires_checkpoint(self) -> None:
        root = self._workspace()
        boundary = WorkerExecutionBoundary(root)
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                self._task(),
                command=[sys.executable, "worker.py"],
            )

    def test_checkpoint_must_attest_isolation(self) -> None:
        root = self._workspace()
        script = self._script(root, "worker.py", "print('ok')\n")
        boundary = WorkerExecutionBoundary(
            root,
            checkpoint=lambda request: {"checkpoint_id": "CP-1", "isolated": False},
            allowed_commands=[sys.executable],
            process_sandbox=self._sandbox(root),
        )
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                self._task(),
                command=[sys.executable, script.name],
            )

    def test_allowed_command_executes_in_workspace(self) -> None:
        root = self._workspace()
        script = self._script(root, "worker.py", "print('ok')\n")
        seen = []

        def checkpoint(request):
            seen.append(request.workspace_root)
            return {"checkpoint_id": "CP-1", "isolated": True}

        boundary = WorkerExecutionBoundary(
            root,
            checkpoint=checkpoint,
            allowed_commands=[sys.executable],
            process_sandbox=self._sandbox(root),
        )
        result = boundary.execute(
            self._assignment(),
            self._task(),
            command=[sys.executable, script.name],
        )

        self.assertTrue(result.succeeded)
        self.assertEqual(result.stdout.strip(), "ok")
        self.assertEqual(seen, [str(root.resolve())])
        self.assertEqual(
            result.checkpoint,
            {"checkpoint_id": "CP-1", "isolated": True},
        )

    def test_process_sandbox_is_auto_wrapped_by_terminal_executor(self) -> None:
        root = self._workspace()
        boundary = self._boundary(root)
        self.assertIsInstance(boundary.terminal_executor, TerminalExecutor)
        self.assertIs(boundary.terminal_executor.sandbox, boundary.process_sandbox)

    def test_terminal_policy_is_enforced_before_process_launch(self) -> None:
        root = self._workspace()
        script = self._script(root, "worker.py", "print('ok')\n")
        terminal_policy = TerminalPolicy([TerminalCommandPolicy("pytest")])
        sandbox = self._sandbox(root)
        boundary = WorkerExecutionBoundary(
            root,
            checkpoint=self._checkpoint,
            allowed_commands=[sys.executable],
            process_sandbox=sandbox,
            terminal_executor=TerminalExecutor(
                sandbox,
                terminal_policy=terminal_policy,
            ),
        )

        with self.assertRaises(ProcessSandboxSafetyStop):
            boundary.execute(
                self._assignment(),
                self._task(),
                command=[sys.executable, script.name],
            )

    def test_non_allowlisted_command_is_rejected(self) -> None:
        root = self._workspace()
        boundary = self._boundary(root)
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                self._task(),
                command=["powershell", "-Command", "Write-Output ok"],
            )

    def test_shell_and_inline_interpreter_launchers_are_rejected(self) -> None:
        root = self._workspace()
        boundary = self._boundary(root)
        for command in (
            [sys.executable, "-c", "print('ok')"],
            [sys.executable, "-m", "http.server"],
        ):
            with self.subTest(command=command), self.assertRaises(WorkerExecutionSafetyStop):
                boundary.execute(
                    self._assignment(),
                    self._task(),
                    command=command,
                )

    def test_path_escape_is_rejected(self) -> None:
        root = self._workspace()
        boundary = self._boundary(root)
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                self._task(),
                command=[sys.executable, "worker.py"],
                targets=["../outside.txt"],
            )

    def test_absolute_outside_script_is_rejected(self) -> None:
        root = self._workspace()
        outside = Path(tempfile.gettempdir()).resolve() / "external-worker-test.py"
        outside.write_text("print('outside')\n", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)

        boundary = self._boundary(root)
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                self._task(),
                command=[sys.executable, str(outside)],
            )

    def test_standby_assignment_cannot_execute_directly(self) -> None:
        root = self._workspace()
        self._script(root, "worker.py", "print('ok')\n")
        boundary = self._boundary(root)
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(standby=True),
                self._task(),
                command=[sys.executable, "worker.py"],
            )

    def test_timeout_is_safe_stop(self) -> None:
        root = self._workspace()
        self._script(root, "worker.py", "import time; time.sleep(2)\n")
        boundary = self._boundary(root, timeout=0.05)
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                self._task(),
                command=[sys.executable, "worker.py"],
            )

    def test_output_is_bounded(self) -> None:
        root = self._workspace()
        self._script(root, "worker.py", "print('x' * 1000)\n")
        boundary = WorkerExecutionBoundary(
            root,
            checkpoint=self._checkpoint,
            allowed_commands=[sys.executable],
            process_sandbox=self._sandbox(root),
            timeout_seconds=3,
            max_output_chars=256,
        )
        result = boundary.execute(
            self._assignment(),
            self._task(),
            command=[sys.executable, "worker.py"],
        )
        self.assertTrue(result.truncated)
        self.assertEqual(len(result.stdout), 256)

    def test_task_and_assignment_identity_must_match(self) -> None:
        root = self._workspace()
        self._script(root, "worker.py", "print('ok')\n")
        boundary = self._boundary(root)
        task = self._task()
        task["task_id"] = "TASK-2"
        with self.assertRaises(WorkerExecutionSafetyStop):
            boundary.execute(
                self._assignment(),
                task,
                command=[sys.executable, "worker.py"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
