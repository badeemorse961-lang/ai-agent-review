from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from secret_redaction import redact_text


SCHEMA_VERSION = 1
DEFAULT_MAX_TARGETS = 64
DEFAULT_MAX_COMMIT_MESSAGE_CHARS = 256


class GitMutationPolicyError(ValueError):
    """Base error for task-scoped Git mutation policy failures."""


class GitMutationSafetyStop(GitMutationPolicyError):
    """Raised when repository mutation cannot be proven task-scoped and safe."""


@dataclass(frozen=True)
class GitMutationRequest:
    """Immutable, task-scoped description of an allowed local Git mutation."""

    task_id: str
    worker_id: str
    operation: str
    targets: tuple[str, ...] = ()
    commit_message: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "operation": self.operation,
            "targets": list(self.targets),
            "commit_message_present": bool(self.commit_message),
        }


class GitMutationPolicy:
    """Allow only narrow local repository mutations bound to validated targets."""

    _ALLOWED_OPERATIONS = frozenset({"stage", "commit"})
    _FORBIDDEN_TOKENS = frozenset(
        {
            "-c",
            "--config",
            "--config-env",
            "--exec-path",
            "--git-dir",
            "--work-tree",
            "-C",
            "--no-verify",
            "--amend",
            "--allow-empty",
            "--reset-author",
            "--signoff",
            "--gpg-sign",
            "--no-gpg-sign",
        }
    )

    def __init__(
        self,
        *,
        max_targets: int = DEFAULT_MAX_TARGETS,
        max_commit_message_chars: int = DEFAULT_MAX_COMMIT_MESSAGE_CHARS,
    ) -> None:
        if max_targets < 1:
            raise ValueError("max_targets must be positive")
        if max_commit_message_chars < 16:
            raise ValueError("max_commit_message_chars must be >= 16")
        self.max_targets = int(max_targets)
        self.max_commit_message_chars = int(max_commit_message_chars)

    def validate_request(
        self,
        *,
        task_id: str,
        worker_id: str,
        operation: str,
        targets: Iterable[str] = (),
        commit_message: str = "",
        workspace_root: Path,
    ) -> GitMutationRequest:
        task = self._non_empty_identity(task_id, "task_id")
        worker = self._non_empty_identity(worker_id, "worker_id")
        op = self._non_empty_identity(operation, "operation").lower()
        if op not in self._ALLOWED_OPERATIONS:
            raise GitMutationSafetyStop(
                f"Git mutation operation is not allowlisted: {operation!r}"
            )

        root = self._validate_repository_root(workspace_root)
        normalized_targets = self._normalize_targets(targets, root)

        if op == "stage" and not normalized_targets:
            raise GitMutationSafetyStop("Staging requires at least one validated target")
        if op == "commit":
            self._validate_commit_message(commit_message)
            if not normalized_targets:
                raise GitMutationSafetyStop("Commit requires at least one validated target")
        elif commit_message:
            raise GitMutationSafetyStop("Commit message is only valid for commit operations")

        return GitMutationRequest(
            task_id=task,
            worker_id=worker,
            operation=op,
            targets=normalized_targets,
            commit_message=commit_message.strip(),
        )

    def command(self, request: GitMutationRequest) -> tuple[str, ...]:
        if not isinstance(request, GitMutationRequest):
            raise GitMutationSafetyStop("Mutation command requires a GitMutationRequest")
        if request.operation == "stage":
            return ("git", "add", "--", *request.targets)
        if request.operation == "commit":
            return ("git", "commit", "-m", request.commit_message)
        raise GitMutationSafetyStop(
            f"Git mutation operation is not allowlisted: {request.operation!r}"
        )

    def validate_command(
        self,
        command: Sequence[str],
        *,
        request: GitMutationRequest,
        workspace_root: Path,
    ) -> tuple[str, ...]:
        if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):
            raise GitMutationSafetyStop("Git mutation command must be an argument sequence")
        args = tuple(str(item) for item in command)
        if not args or not args[0].strip():
            raise GitMutationSafetyStop("Git mutation command is empty")
        executable = Path(args[0]).name.lower()
        if executable.endswith(".exe"):
            executable = executable[:-4]
        if executable != "git":
            raise GitMutationSafetyStop("Git mutation command must invoke Git")

        if any(token.lower() in self._FORBIDDEN_TOKENS for token in args[1:]):
            raise GitMutationSafetyStop("Forbidden Git mutation option detected")
        if any(
            token.lower().startswith(("--config=", "--git-dir=", "--work-tree="))
            for token in args[1:]
        ):
            raise GitMutationSafetyStop("Git repository/configuration override is forbidden")

        expected = self.command(request)
        if args != expected:
            raise GitMutationSafetyStop(
                "Git mutation command does not exactly match the validated request"
            )

        self._validate_repository_root(workspace_root)
        if request.operation == "stage":
            self._validate_command_targets(args[3:], request.targets, workspace_root)
        return args

    def _normalize_targets(self, targets: Iterable[str], workspace_root: Path) -> tuple[str, ...]:
        seen: set[str] = set()
        normalized: list[str] = []
        for raw in targets:
            if not isinstance(raw, str) or not raw.strip():
                raise GitMutationSafetyStop("Git mutation targets must be non-empty strings")

            raw_text = raw.strip()
            raw_parts = [part for part in raw_text.replace("\\", "/").split("/") if part]
            if any(part in {".", ".."} for part in raw_parts):
                raise GitMutationSafetyStop(f"Unsafe Git mutation target: {raw!r}")

            path = Path(raw_text)
            if path.is_absolute() or path.drive or path.root:
                raise GitMutationSafetyStop(
                    f"Git mutation target must be workspace-relative: {raw!r}"
                )

            candidate = (workspace_root / path).resolve(strict=False)
            try:
                candidate.relative_to(workspace_root)
            except ValueError as exc:
                raise GitMutationSafetyStop(
                    f"Git mutation target escapes workspace: {raw!r}"
                ) from exc

            canonical = candidate.relative_to(workspace_root).as_posix()
            if canonical in seen:
                raise GitMutationSafetyStop(
                    f"Duplicate Git mutation target: {canonical!r}"
                )
            seen.add(canonical)
            normalized.append(canonical)
            if len(normalized) > self.max_targets:
                raise GitMutationSafetyStop("Too many Git mutation targets")
        return tuple(normalized)

    def _validate_command_targets(
        self,
        values: Sequence[str],
        expected: Sequence[str],
        workspace_root: Path,
    ) -> None:
        normalized = self._normalize_targets(values, workspace_root)
        if tuple(normalized) != tuple(expected):
            raise GitMutationSafetyStop("Command target set differs from validated target set")

    @staticmethod
    def _validate_repository_root(workspace_root: Path) -> Path:
        root = Path(workspace_root).resolve()
        if not root.exists() or not root.is_dir():
            raise GitMutationSafetyStop("Git workspace root must be an existing directory")
        git_dir = root / ".git"
        if not git_dir.exists():
            raise GitMutationSafetyStop(
                "Git mutation requires the active workspace to be a Git repository"
            )
        return root

    def _validate_commit_message(self, message: str) -> None:
        if not isinstance(message, str) or not message.strip():
            raise GitMutationSafetyStop("Commit message must be a non-empty string")
        cleaned = message.strip()
        if len(cleaned) > self.max_commit_message_chars:
            raise GitMutationSafetyStop("Commit message exceeds the policy limit")
        if "\n" in message or "\r" in message:
            raise GitMutationSafetyStop("Commit message must be single-line")
        if any(ord(char) < 32 and char not in "\t" for char in message):
            raise GitMutationSafetyStop("Commit message contains control characters")
        if redact_text(cleaned) != cleaned:
            raise GitMutationSafetyStop(
                "Commit message contains credential-like material and cannot enter Git history"
            )

    @staticmethod
    def _non_empty_identity(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise GitMutationSafetyStop(f"{field} must be a non-empty string")
        return value.strip()
