from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from process_sandbox import ProcessSandbox


SCHEMA_VERSION = 1
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_OUTPUT_CHARS = 20_000
DEFAULT_ALLOWED_COMMANDS = ("python", "pytest")


class WorkerExecutionError(ValueError):
    """Base error for guarded worker execution."""


class WorkerExecutionSafetyStop(WorkerExecutionError):
    """Raised when execution cannot be proven safe before launch."""


@dataclass(frozen=True)
class ExecutionRequest:
    task_id: str
    role: str
    worker_id: str
    workspace_root: str
    command: tuple[str, ...]
    targets: tuple[str, ...]
    timeout_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "role": self.role,
            "worker_id": self.worker_id,
            "workspace_root": self.workspace_root,
            "command": list(self.command),
            "targets": list(self.targets),
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True)
class ExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool
    checkpoint: Any

    @property
    def succeeded(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
            "checkpoint": self.checkpoint,
            "succeeded": self.succeeded,
        }


CheckpointHook = Callable[[ExecutionRequest], Mapping[str, Any]]
ExecutorHook = Callable[[ExecutionRequest], tuple[int, str, str, bool]]


class WorkerExecutionBoundary:
    """Guarded execution boundary for one already-assigned worker task.

    The worker may operate freely inside the explicit active workspace, but the
    boundary rejects declared targets outside that workspace and rejects shell
    wrappers or inline interpreter launchers. A process cwd alone is not treated
    as a complete isolation guarantee: the checkpoint hook must explicitly attest
    that execution is isolated before the executor is allowed to launch.

    An optional ``ProcessSandbox`` adds explicit tool-path validation, process
    group isolation, environment minimization, and bounded child-process launch.
    """

    _PATH_LIKE_SUFFIXES = {
        ".cfg",
        ".ini",
        ".json",
        ".py",
        ".toml",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }

    def __init__(
        self,
        workspace_root: Path,
        *,
        allowed_commands: Sequence[str] = DEFAULT_ALLOWED_COMMANDS,
        checkpoint: Optional[CheckpointHook] = None,
        executor: Optional[ExecutorHook] = None,
        process_sandbox: Optional[ProcessSandbox] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        if not self.workspace_root.exists() or not self.workspace_root.is_dir():
            raise WorkerExecutionSafetyStop(
                f"Workspace root must be an existing directory: {self.workspace_root}"
            )

        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise WorkerExecutionError("timeout_seconds must be positive")
        if not isinstance(max_output_chars, int) or max_output_chars < 256:
            raise WorkerExecutionError("max_output_chars must be an integer >= 256")

        normalized = {
            str(item).strip().lower()
            for item in allowed_commands
            if str(item).strip()
        }
        if not normalized:
            raise WorkerExecutionError("At least one allowed command is required")

        self.allowed_commands = normalized
        self.checkpoint = checkpoint
        self.executor = executor or self._subprocess_executor
        self.process_sandbox = process_sandbox
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_chars = max_output_chars

        if self.process_sandbox is not None and self.process_sandbox.policy.workspace_root != self.workspace_root:
            raise WorkerExecutionSafetyStop(
                "Process sandbox workspace must match worker workspace"
            )

    def execute(
        self,
        assignment: Mapping[str, Any],
        task: Mapping[str, Any],
        *,
        command: Sequence[str],
        targets: Iterable[str] = (),
    ) -> ExecutionResult:
        request = self._validate_and_build_request(
            assignment,
            task,
            command=command,
            targets=targets,
        )

        if self.checkpoint is None:
            raise WorkerExecutionSafetyStop(
                "Execution requires an isolated checkpoint hook"
            )

        checkpoint = self.checkpoint(request)
        if not isinstance(checkpoint, Mapping) or checkpoint.get("isolated") is not True:
            raise WorkerExecutionSafetyStop(
                "Checkpoint must explicitly attest isolated execution"
            )

        returncode, stdout, stderr, timed_out = self.executor(request)

        stdout, stdout_truncated = self._bound_output(stdout)
        stderr, stderr_truncated = self._bound_output(stderr)
        result = ExecutionResult(
            returncode=int(returncode),
            stdout=stdout,
            stderr=stderr,
            timed_out=bool(timed_out),
            truncated=stdout_truncated or stderr_truncated,
            checkpoint=checkpoint,
        )

        if result.timed_out:
            raise WorkerExecutionSafetyStop(
                f"Worker execution timed out after {request.timeout_seconds:g}s"
            )

        return result

    def _validate_and_build_request(
        self,
        assignment: Mapping[str, Any],
        task: Mapping[str, Any],
        *,
        command: Sequence[str],
        targets: Iterable[str],
    ) -> ExecutionRequest:
        if not isinstance(assignment, Mapping):
            raise WorkerExecutionSafetyStop("Worker assignment must be a mapping")
        if not isinstance(task, Mapping):
            raise WorkerExecutionSafetyStop("Worker task must be a mapping")

        task_id = self._non_empty_string(assignment.get("task_id"), "assignment.task_id")
        role = self._non_empty_string(assignment.get("role"), "assignment.role")
        worker_id = self._non_empty_string(assignment.get("worker_id"), "assignment.worker_id")
        if assignment.get("standby") is True:
            raise WorkerExecutionSafetyStop(
                "Standby worker assignments require an explicit promotion boundary before execution"
            )

        task_task_id = self._non_empty_string(task.get("task_id"), "task.task_id")
        task_role = self._non_empty_string(task.get("role"), "task.role")
        if task_task_id != task_id or task_role != role:
            raise WorkerExecutionSafetyStop(
                "Worker assignment does not match the execution task"
            )

        acceptance = task.get("acceptance_criteria")
        if not isinstance(acceptance, list) or not acceptance or not all(
            isinstance(item, str) and item.strip() for item in acceptance
        ):
            raise WorkerExecutionSafetyStop(
                f"Task {task_id!r} requires non-empty acceptance criteria"
            )

        authority = task.get("authority")
        if isinstance(authority, Mapping):
            if authority.get("execution_authorized", False) is not False:
                raise WorkerExecutionSafetyStop(
                    "Task metadata cannot elevate execution authority"
                )
            if authority.get("mutation_allowed", False) is True:
                raise WorkerExecutionSafetyStop(
                    "Task metadata cannot grant unrestricted mutation authority"
                )

        normalized_command = self._validate_command(command)
        normalized_targets = tuple(
            self._validate_target(target) for target in targets
        )

        return ExecutionRequest(
            task_id=task_id,
            role=role,
            worker_id=worker_id,
            workspace_root=str(self.workspace_root),
            command=normalized_command,
            targets=normalized_targets,
            timeout_seconds=self.timeout_seconds,
        )

    def _validate_command(self, command: Sequence[str]) -> tuple[str, ...]:
        if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):
            raise WorkerExecutionSafetyStop("Command must be an argument sequence")
        if not command:
            raise WorkerExecutionSafetyStop("Command must not be empty")

        args = tuple(str(item) for item in command)
        if any(not item.strip() for item in args):
            raise WorkerExecutionSafetyStop("Command arguments must be non-empty strings")

        executable = Path(args[0]).name.lower()
        allowed_names = {Path(item).name.lower() for item in self.allowed_commands}
        if os.name == "nt" and executable.endswith(".exe"):
            executable_stem = executable[:-4]
            allowed_names = {
                name[:-4] if name.endswith(".exe") else name
                for name in allowed_names
            }
            executable = executable_stem

        if executable not in allowed_names:
            raise WorkerExecutionSafetyStop(
                f"Command executable is not allowlisted: {args[0]!r}"
            )

        forbidden = {
            "shell",
            "cmd",
            "/c",
            "powershell",
            "pwsh",
            "bash",
            "sh",
        }
        inline_interpreter_flags = {"-c", "/c", "-m"}
        if any(item.lower() in forbidden for item in args):
            raise WorkerExecutionSafetyStop(
                "Shell-wrapper arguments are not permitted at the worker boundary"
            )
        if executable in {"python", "python3", "pytest"} and any(
            item.lower() in inline_interpreter_flags for item in args[1:]
        ):
            raise WorkerExecutionSafetyStop(
                "Inline interpreter/module launchers are not permitted; execute workspace files instead"
            )

        for item in args[1:]:
            if self._looks_like_path_argument(item):
                self._validate_target(item)

        return args

    @classmethod
    def _looks_like_path_argument(cls, value: str) -> bool:
        path = Path(value)
        return (
            path.is_absolute()
            or "/" in value
            or "\\" in value
            or path.suffix.lower() in cls._PATH_LIKE_SUFFIXES
        )

    def _validate_target(self, target: str) -> str:
        if not isinstance(target, str) or not target.strip():
            raise WorkerExecutionSafetyStop("Execution targets must be non-empty paths")

        candidate = Path(target)
        resolved = candidate if candidate.is_absolute() else self.workspace_root / candidate
        resolved = resolved.resolve(strict=False)

        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise WorkerExecutionSafetyStop(
                f"Execution target escapes workspace: {target!r}"
            ) from exc

        current = self.workspace_root
        relative_parts = resolved.relative_to(self.workspace_root).parts
        for part in relative_parts:
            current = current / part
            if current.is_symlink():
                raise WorkerExecutionSafetyStop(
                    f"Symlink/junction target is not permitted: {target!r}"
                )

        return resolved.relative_to(self.workspace_root).as_posix()

    def _subprocess_executor(
        self,
        request: ExecutionRequest,
    ) -> tuple[int, str, str, bool]:
        if self.process_sandbox is not None:
            result = self.process_sandbox.run(
                request.command,
                target_paths=request.targets,
            )
            return result.returncode, result.stdout, result.stderr, result.timed_out

        try:
            completed = subprocess.run(
                list(request.command),
                cwd=request.workspace_root,
                shell=False,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
            )
            return completed.returncode, completed.stdout, completed.stderr, False
        except subprocess.TimeoutExpired as exc:
            stdout = self._text_from_timeout(exc.stdout)
            stderr = self._text_from_timeout(exc.stderr)
            return -1, stdout, stderr, True

    @staticmethod
    def _text_from_timeout(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def _bound_output(self, value: Any) -> tuple[str, bool]:
        text = "" if value is None else str(value)
        if len(text) <= self.max_output_chars:
            return text, False
        return text[: self.max_output_chars], True

    @staticmethod
    def _non_empty_string(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise WorkerExecutionSafetyStop(f"{field} must be a non-empty string")
        return value.strip()


def execute_worker_task(
    workspace_root: Path,
    assignment: Mapping[str, Any],
    task: Mapping[str, Any],
    *,
    command: Sequence[str],
    targets: Iterable[str] = (),
    allowed_commands: Sequence[str] = DEFAULT_ALLOWED_COMMANDS,
    checkpoint: Optional[CheckpointHook] = None,
    executor: Optional[ExecutorHook] = None,
    process_sandbox: Optional[ProcessSandbox] = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
) -> ExecutionResult:
    boundary = WorkerExecutionBoundary(
        workspace_root,
        allowed_commands=allowed_commands,
        checkpoint=checkpoint,
        executor=executor,
        process_sandbox=process_sandbox,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )
    return boundary.execute(
        assignment,
        task,
        command=command,
        targets=targets,
    )


if __name__ == "__main__":
    print("Worker execution boundary ready.")
