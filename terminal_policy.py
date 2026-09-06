from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from git_safety import GitSafetyPolicy
from process_sandbox import ProcessSandboxSafetyStop


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class TerminalCommandPolicy:
    """Explicit policy for one development executable."""

    executable: str
    allowed_subcommands: tuple[str, ...] = ()
    forbidden_arguments: tuple[str, ...] = ()
    max_arguments: int = 32
    validate_path_arguments: bool = True

    @property
    def normalized_executable(self) -> str:
        name = Path(self.executable).name.lower()
        return name[:-4] if name.endswith(".exe") else name


class TerminalPolicy:
    """Validate command shape before it reaches the process sandbox."""

    DEFAULT_COMMANDS = (
        TerminalCommandPolicy("python", forbidden_arguments=("-c", "-m")),
        TerminalCommandPolicy("pytest", forbidden_arguments=("-c", "-m")),
        TerminalCommandPolicy("git"),
    )

    _SHELL_TOKENS = frozenset(
        {
            "cmd",
            "/c",
            "powershell",
            "pwsh",
            "bash",
            "sh",
            "zsh",
            "fish",
            "shell",
            "&&",
            "||",
            ";",
            "|",
            ">",
            ">>",
            "<",
        }
    )
    _PATH_SUFFIXES = frozenset(
        {
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
            ".md",
            ".rst",
        }
    )

    def __init__(
        self,
        policies: Iterable[TerminalCommandPolicy] | None = None,
        *,
        max_arguments: int = 32,
        git_safety_policy: GitSafetyPolicy | None = None,
    ) -> None:
        source = tuple(policies or self.DEFAULT_COMMANDS)
        if not source:
            raise ValueError("At least one terminal command policy is required")
        if max_arguments < 1:
            raise ValueError("max_arguments must be positive")
        if any(policy.max_arguments < 0 for policy in source):
            raise ValueError("Policy max_arguments cannot be negative")

        self._policies = {
            policy.normalized_executable: policy
            for policy in source
        }
        self.max_arguments = int(max_arguments)
        self.git_safety_policy = git_safety_policy or GitSafetyPolicy()

    def validate(
        self,
        command: Sequence[str],
        *,
        workspace_root: Path,
        external_reads: Mapping[Path | str, str] | None = None,
    ) -> tuple[str, ...]:
        if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):
            raise ProcessSandboxSafetyStop(
                "Terminal command must be an argument sequence"
            )
        args = tuple(str(item) for item in command)
        if not args or any(not item.strip() for item in args):
            raise ProcessSandboxSafetyStop(
                "Terminal command arguments must be non-empty"
            )
        if len(args) - 1 > self.max_arguments:
            raise ProcessSandboxSafetyStop("Terminal command has too many arguments")

        executable_path = Path(args[0])
        normalized = executable_path.name.lower()
        if normalized.endswith(".exe"):
            normalized = normalized[:-4]

        policy = self._policies.get(normalized)
        if policy is None:
            raise ProcessSandboxSafetyStop(
                f"Terminal executable is not allowlisted: {args[0]!r}"
            )
        if len(args) - 1 > policy.max_arguments:
            raise ProcessSandboxSafetyStop(
                f"Terminal command exceeds argument limit for {normalized!r}"
            )

        if normalized == "git":
            self.git_safety_policy.validate(
                args,
                workspace_root=workspace_root,
            )
            return args

        lowered = tuple(item.lower() for item in args[1:])
        forbidden = {item.lower() for item in policy.forbidden_arguments}
        if any(item in forbidden for item in lowered):
            raise ProcessSandboxSafetyStop(
                f"Forbidden argument for terminal executable {normalized!r}"
            )
        if any(item in self._SHELL_TOKENS for item in lowered):
            raise ProcessSandboxSafetyStop(
                "Shell wrappers and shell operators are forbidden"
            )

        if policy.allowed_subcommands:
            if not lowered or lowered[0] not in {
                item.lower() for item in policy.allowed_subcommands
            }:
                raise ProcessSandboxSafetyStop(
                    f"Subcommand is not allowlisted for {normalized!r}"
                )

        if policy.validate_path_arguments:
            self._validate_path_arguments(
                args[1:],
                workspace_root.resolve(),
                external_reads or {},
            )

        return args

    @classmethod
    def _validate_path_arguments(
        cls,
        args: Sequence[str],
        workspace_root: Path,
        external_reads: Mapping[Path | str, str],
    ) -> None:
        external = tuple(
            (Path(root).resolve(), str(access).lower())
            for root, access in external_reads.items()
        )

        for value in args:
            path = Path(value)
            if not cls._looks_like_path(path, value):
                continue

            candidate = (
                path.resolve(strict=False)
                if path.is_absolute()
                else (workspace_root / path).resolve(strict=False)
            )
            if _is_within(candidate, workspace_root):
                continue

            if any(
                access in {"read", "read_write"}
                and _is_within(candidate, root)
                for root, access in external
            ):
                continue

            raise ProcessSandboxSafetyStop(
                f"Terminal path argument is outside authorized resources: {value!r}"
            )

    @classmethod
    def _looks_like_path(cls, path: Path, value: str) -> bool:
        return (
            path.is_absolute()
            or "/" in value
            or "\\" in value
            or path.suffix.lower() in cls._PATH_SUFFIXES
        )


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False
