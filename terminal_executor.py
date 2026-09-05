from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from process_sandbox import ProcessResult, ProcessSandbox
from terminal_policy import TerminalCommandPolicy, TerminalPolicy


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TerminalExecutionRequest:
    command: tuple[str, ...]
    external_reads: tuple[str, ...] = ()
    external_writes: tuple[str, ...] = ()


class TerminalExecutor:
    """Policy-first terminal execution facade.

    The terminal policy decides whether the command shape is allowed. The
    process sandbox then enforces the existing tool/resource/process boundary.
    Neither layer is a replacement for the Execution Gate.
    """

    def __init__(
        self,
        sandbox: ProcessSandbox,
        *,
        terminal_policy: TerminalPolicy | None = None,
    ) -> None:
        self.sandbox = sandbox
        self.terminal_policy = terminal_policy or TerminalPolicy(
            TerminalCommandPolicy(
                executable=command,
                forbidden_arguments=("-c", "-m")
                if Path(command).name.lower().removesuffix(".exe") in {"python", "pytest"}
                else (),
            )
            for command in ("python", "pytest")
        )

    def validate(
        self,
        command: Sequence[str],
        *,
        external_reads: Sequence[str] = (),
    ) -> TerminalExecutionRequest:
        normalized = self.terminal_policy.validate(
            command,
            workspace_root=self.sandbox.policy.workspace_root,
            external_reads={path: "read" for path in external_reads},
        )
        return TerminalExecutionRequest(
            command=normalized,
            external_reads=tuple(str(path) for path in external_reads),
        )

    def run(
        self,
        command: Sequence[str],
        *,
        target_paths: Sequence[str] = (),
        external_reads: Sequence[str] = (),
        external_writes: Sequence[str] = (),
    ) -> ProcessResult:
        request = self.validate(command, external_reads=external_reads)
        return self.sandbox.run(
            request.command,
            target_paths=target_paths,
            external_reads=request.external_reads,
            external_writes=external_writes,
        )
