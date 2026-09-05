from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from sandbox_policy import SandboxPolicySafetyStop, WorkspaceResourcePolicy


SCHEMA_VERSION = 1
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_OUTPUT_CHARS = 20_000


class ProcessSandboxError(ValueError):
    """Base error for process sandbox failures."""


class ProcessSandboxSafetyStop(ProcessSandboxError):
    """Raised when safe process launch cannot be proven."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool
    isolated_process_group: bool
    containment_mode: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "truncated": self.truncated,
            "isolated_process_group": self.isolated_process_group,
            "containment_mode": self.containment_mode,
        }


class ProcessSandbox:
    """Launch development tools with explicit process and resource policy.

    This layer provides process-group containment, bounded output, explicit cwd,
    shell-free argument execution, and environment sanitization. It does not
    claim OS-level filesystem isolation: a child process remains capable of
    opening unmanaged paths unless the host supplies a stronger OS sandbox.
    """

    _DEFAULT_ENV_ALLOWLIST = {
        "SYSTEMROOT",
        "WINDIR",
        "PATH",
        "PATHEXT",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
    }
    _REQUEST_ENV_ALLOWLIST = {"TEMP", "TMP", "LANG", "LC_ALL"}
    _PATH_LIKE_SUFFIXES = {
        ".cfg",
        ".ini",
        ".json",
        ".py",
        ".pyc",
        ".toml",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }

    def __init__(
        self,
        policy: WorkspaceResourcePolicy,
        *,
        containment_mode: str = "workspace_guarded",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
    ) -> None:
        if containment_mode not in {"workspace_guarded", "strict_os_required"}:
            raise ProcessSandboxError(
                "containment_mode must be 'workspace_guarded' or 'strict_os_required'"
            )
        if containment_mode == "strict_os_required":
            raise ProcessSandboxSafetyStop(
                "No portable OS filesystem sandbox backend is installed; "
                "strict_os_required therefore fails closed"
            )
        if timeout_seconds <= 0:
            raise ProcessSandboxError("timeout_seconds must be positive")
        if max_output_chars < 256:
            raise ProcessSandboxError("max_output_chars must be >= 256")

        self.policy = policy
        self.containment_mode = containment_mode
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_chars = int(max_output_chars)

    def run(
        self,
        command: Sequence[str],
        *,
        target_paths: Sequence[Path | str] = (),
        env: Mapping[str, str] | None = None,
        external_reads: Sequence[Path | str] = (),
        external_writes: Sequence[Path | str] = (),
    ) -> ProcessResult:
        normalized_command = self._validate_command(command)
        cwd = self.policy.workspace_root

        try:
            for target in target_paths:
                self.policy.validate_workspace_path(target)
            for path in external_reads:
                self.policy.validate_external_path(path, access="read")
            for path in external_writes:
                self.policy.validate_external_path(path, access="write")

            resolved_executable = self.policy.validate_tool_executable(normalized_command[0])
            self._validate_command_paths(normalized_command[1:])
        except SandboxPolicySafetyStop as exc:
            raise ProcessSandboxSafetyStop(str(exc)) from exc
        except FileNotFoundError as exc:
            raise ProcessSandboxSafetyStop(
                f"Approved tool does not exist: {normalized_command[0]!r}"
            ) from exc

        normalized_command = (str(resolved_executable), *normalized_command[1:])
        child_env = self._build_environment(env)
        creationflags = 0
        start_new_session = False

        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            start_new_session = True

        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                list(normalized_command),
                cwd=str(cwd),
                env=child_env,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                start_new_session=start_new_session,
            )
            stdout, stderr = process.communicate(timeout=self.timeout_seconds)
            return self._result(
                process.returncode,
                stdout,
                stderr,
                timed_out=False,
                isolated_process_group=True,
            )
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                self._terminate_process_tree(process)
                stdout, stderr = process.communicate()
            else:
                stdout, stderr = self._to_text(exc.stdout), self._to_text(exc.stderr)
            return self._result(
                -1,
                stdout,
                self._to_text(stderr) + "\nPROCESS TIMEOUT",
                timed_out=True,
                isolated_process_group=True,
            )
        except OSError as exc:
            raise ProcessSandboxSafetyStop(
                f"Failed to launch approved tool: {exc}"
            ) from exc

    def _validate_command(self, command: Sequence[str]) -> tuple[str, ...]:
        if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):
            raise ProcessSandboxSafetyStop("Command must be an argument sequence")
        args = tuple(str(item) for item in command)
        if not args or any(not item.strip() for item in args):
            raise ProcessSandboxSafetyStop("Command and arguments must be non-empty")
        if any(
            item.lower()
            in {"cmd", "/c", "powershell", "pwsh", "bash", "sh", "-c", "-m"}
            for item in args
        ):
            raise ProcessSandboxSafetyStop("Shell wrappers and inline launchers are forbidden")
        return args

    def _validate_command_paths(self, args: Sequence[str]) -> None:
        for value in args:
            if not self._looks_like_path_argument(value):
                continue
            try:
                self.policy.validate_workspace_path(value)
            except SandboxPolicySafetyStop:
                try:
                    self.policy.validate_external_path(value, access="read")
                except SandboxPolicySafetyStop as exc:
                    raise ProcessSandboxSafetyStop(
                        f"Command path is not authorized: {value!r}"
                    ) from exc

    @classmethod
    def _looks_like_path_argument(cls, value: str) -> bool:
        path = Path(value)
        return (
            path.is_absolute()
            or "/" in value
            or "\\" in value
            or path.suffix.lower() in cls._PATH_LIKE_SUFFIXES
        )

    def _build_environment(self, requested: Mapping[str, str] | None) -> dict[str, str]:
        requested = requested or {}
        unknown = {
            str(key).upper()
            for key in requested
            if str(key).upper() not in self._REQUEST_ENV_ALLOWLIST
            and not str(key).upper().startswith("AGENT_")
        }
        if unknown:
            raise ProcessSandboxSafetyStop(
                f"Environment contains non-allowlisted variables: {sorted(unknown)}"
            )

        base = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in self._DEFAULT_ENV_ALLOWLIST
            and "KEY" not in key.upper()
            and "TOKEN" not in key.upper()
            and "SECRET" not in key.upper()
            and "PASSWORD" not in key.upper()
            and "AUTH" not in key.upper()
        }
        for key, value in requested.items():
            upper = str(key).upper()
            if upper in self._REQUEST_ENV_ALLOWLIST or upper.startswith("AGENT_"):
                base[str(key)] = str(value)
        return base

    def _terminate_process_tree(self, process: subprocess.Popen[str]) -> None:
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    shell=False,
                )
            except OSError:
                try:
                    process.kill()
                except OSError:
                    pass
            return

        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            try:
                process.kill()
            except OSError:
                pass

    def _result(
        self,
        returncode: int,
        stdout: object,
        stderr: object,
        *,
        timed_out: bool,
        isolated_process_group: bool,
    ) -> ProcessResult:
        stdout_text, stdout_truncated = self._bound(self._to_text(stdout))
        stderr_text, stderr_truncated = self._bound(self._to_text(stderr))
        return ProcessResult(
            returncode=int(returncode),
            stdout=stdout_text,
            stderr=stderr_text,
            timed_out=timed_out,
            truncated=stdout_truncated or stderr_truncated,
            isolated_process_group=isolated_process_group,
            containment_mode=self.containment_mode,
        )

    def _bound(self, text: str) -> tuple[str, bool]:
        if len(text) <= self.max_output_chars:
            return text, False
        return text[: self.max_output_chars], True

    @staticmethod
    def _to_text(value: object) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)
