from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Sequence

from process_sandbox import ProcessResult, ProcessSandbox, ProcessSandboxSafetyStop
from sandbox_policy import WorkspaceResourcePolicy


class ExecutionGateProcessRunner:
    """Run gate-owned test commands through the shared process boundary."""

    def __init__(
        self,
        workspace_root: Path,
        *,
        timeout_seconds: float,
        max_output_chars: int = 20_000,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        pytest_executable = shutil.which("pytest")
        if not pytest_executable:
            raise ProcessSandboxSafetyStop(
                "Pytest executable could not be resolved from the active environment"
            )
        pytest_path = Path(pytest_executable).resolve(strict=True)
        policy = WorkspaceResourcePolicy(
            self.workspace_root,
            allowed_tool_paths=(pytest_path,),
        )
        self.sandbox = ProcessSandbox(
            policy,
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
        )
        self.pytest_executable = pytest_path

    @staticmethod
    def _agent_environment() -> dict[str, str]:
        """Pass only explicit AGENT_* variables into gate-owned tests.

        ProcessSandbox treats AGENT_* values as explicit request-scoped
        environment and registers each value for exact output redaction. No
        general host environment inheritance is performed here.
        """
        return {
            key: value
            for key, value in os.environ.items()
            if key.upper().startswith("AGENT_")
        }

    def run(self, args: Sequence[str] = ()) -> ProcessResult:
        command = (str(self.pytest_executable), *tuple(args))
        return self.sandbox.run(
            command,
            env=self._agent_environment(),
        )
