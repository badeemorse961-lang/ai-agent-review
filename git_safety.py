from __future__ import annotations

from pathlib import Path
from typing import Sequence

from process_sandbox import ProcessSandboxSafetyStop


SCHEMA_VERSION = 1


class GitSafetyPolicy:
    """Restrict terminal Git access to safe repository-inspection operations.

    Repository mutations such as commit/push/reset/clean remain outside the
    generic terminal path. They require an explicitly designed mutation/control
    plane so Git cannot become an implicit authority to rewrite repository state.
    """

    _SAFE_SUBCOMMANDS = frozenset(
        {
            "status",
            "diff",
            "log",
            "show",
            "branch",
            "rev-parse",
            "ls-files",
        }
    )

    _GLOBAL_OPTIONS = frozenset(
        {
            "-c",
            "--config",
            "--config-env",
            "--exec-path",
            "--html-path",
            "--man-path",
            "--info-path",
            "--paginate",
            "-p",
            "--no-pager",
            "--literal-pathspecs",
            "--glob-pathspecs",
            "--noglob-pathspecs",
            "--icase-pathspecs",
            "--namespace",
            "--super-prefix",
            "--git-dir",
            "--work-tree",
            "-C",
        }
    )

    _ALLOWED_ARGUMENTS = {
        "status": frozenset(
            {"--short", "--porcelain", "--porcelain=v1", "--branch"}
        ),
        "diff": frozenset(
            {"--cached", "--stat", "--name-only", "--name-status", "--check"}
        ),
        "log": frozenset({"--oneline", "--decorate", "--stat"}),
        "show": frozenset(),
        "branch": frozenset({"--show-current", "--list"}),
        "rev-parse": frozenset({"--show-toplevel", "--show-prefix", "--abbrev-ref"}),
        "ls-files": frozenset({"--cached", "--modified", "--others", "--exclude-standard"}),
    }

    _FORBIDDEN_SUBCOMMANDS = frozenset(
        {
            "add",
            "am",
            "apply",
            "bisect",
            "checkout",
            "cherry-pick",
            "clean",
            "clone",
            "commit",
            "config",
            "fetch",
            "gc",
            "init",
            "merge",
            "mv",
            "pull",
            "push",
            "rebase",
            "remote",
            "reset",
            "restore",
            "rm",
            "stash",
            "switch",
            "tag",
            "worktree",
        }
    )

    def validate(
        self,
        command: Sequence[str],
        *,
        workspace_root: Path,
    ) -> tuple[str, ...]:
        if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):
            raise ProcessSandboxSafetyStop("Git command must be an argument sequence")

        args = tuple(str(item) for item in command)
        if not args or not args[0].strip():
            raise ProcessSandboxSafetyStop("Git command is empty")

        normalized = Path(args[0]).name.lower()
        if normalized.endswith(".exe"):
            normalized = normalized[:-4]
        if normalized != "git":
            raise ProcessSandboxSafetyStop("Git safety policy received a non-Git executable")

        root = workspace_root.resolve()
        self._validate_repository_root(root)

        if len(args) < 2:
            raise ProcessSandboxSafetyStop("Git subcommand is required")

        self._reject_global_options(args[1:])
        subcommand = self._first_subcommand(args[1:])

        if subcommand in self._FORBIDDEN_SUBCOMMANDS:
            raise ProcessSandboxSafetyStop(
                f"Git subcommand is forbidden in the terminal boundary: {subcommand!r}"
            )
        if subcommand not in self._SAFE_SUBCOMMANDS:
            raise ProcessSandboxSafetyStop(
                f"Git subcommand is not allowlisted: {subcommand!r}"
            )

        self._validate_shape(subcommand, args[1:], root)
        return args

    @staticmethod
    def _validate_repository_root(workspace_root: Path) -> None:
        if not workspace_root.exists() or not workspace_root.is_dir():
            raise ProcessSandboxSafetyStop("Git workspace root must be an existing directory")

        dot_git = workspace_root / ".git"
        if not dot_git.exists():
            raise ProcessSandboxSafetyStop(
                "Git terminal execution requires the active workspace to be a Git repository"
            )

    def _reject_global_options(self, args: Sequence[str]) -> None:
        for value in args:
            lowered = value.lower()
            if lowered in self._GLOBAL_OPTIONS:
                raise ProcessSandboxSafetyStop(
                    f"Git global option is forbidden: {value!r}"
                )
            if lowered.startswith("--config=") or lowered.startswith("--git-dir="):
                raise ProcessSandboxSafetyStop(
                    f"Git repository/config override is forbidden: {value!r}"
                )
            if lowered.startswith("-c") and lowered != "--check":
                raise ProcessSandboxSafetyStop(
                    f"Git config option is forbidden: {value!r}"
                )

    @staticmethod
    def _first_subcommand(args: Sequence[str]) -> str:
        for value in args:
            if value == "--":
                continue
            if value.startswith("-"):
                continue
            return value.lower()
        return ""

    def _validate_shape(
        self,
        subcommand: str,
        args: Sequence[str],
        workspace_root: Path,
    ) -> None:
        allowed = self._ALLOWED_ARGUMENTS[subcommand]
        positional_seen = False

        for value in args[1:]:
            lowered = value.lower()
            if value == "--":
                positional_seen = True
                continue
            if value.startswith("-"):
                if lowered not in allowed:
                    raise ProcessSandboxSafetyStop(
                        f"Git option is not allowlisted for {subcommand!r}: {value!r}"
                    )
                continue

            if subcommand == "status":
                raise ProcessSandboxSafetyStop(
                    "Git status does not accept positional paths through the terminal boundary"
                )
            if subcommand == "branch" and not positional_seen:
                raise ProcessSandboxSafetyStop(
                    "Git branch names are forbidden; inspection-only branch queries are allowed"
                )
            if subcommand == "rev-parse":
                if lowered != "head":
                    raise ProcessSandboxSafetyStop(
                        "Git rev-parse only permits approved identity queries"
                    )
            elif subcommand in {"diff", "ls-files"}:
                self._validate_relative_workspace_path(value, workspace_root)
            elif subcommand == "show":
                if "/" in value or "\\" in value:
                    raise ProcessSandboxSafetyStop(
                        "Git show cannot receive path-like object arguments through the terminal boundary"
                    )
            elif subcommand == "log":
                raise ProcessSandboxSafetyStop(
                    "Git log positional revisions/paths are not permitted through the terminal boundary"
                )

    @staticmethod
    def _validate_relative_workspace_path(value: str, workspace_root: Path) -> None:
        path = Path(value)
        if path.is_absolute() or value.startswith("~"):
            raise ProcessSandboxSafetyStop(
                f"Git path must be workspace-relative: {value!r}"
            )

        candidate = (workspace_root / path).resolve(strict=False)
        try:
            candidate.relative_to(workspace_root)
        except ValueError as exc:
            raise ProcessSandboxSafetyStop(
                f"Git path escapes the active workspace: {value!r}"
            ) from exc
