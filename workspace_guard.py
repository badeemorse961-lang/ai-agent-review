from __future__ import annotations

import os
from pathlib import Path


class WorkspaceViolation(Exception):
    """Raised when an operation targets a path outside the workspace."""


class WorkspaceGuard:
    def __init__(self, workspace_root: str | Path):
        self.root = Path(workspace_root).expanduser().resolve()

        if not self.root.exists():
            raise FileNotFoundError(
                f"Workspace does not exist: {self.root}"
            )

        if not self.root.is_dir():
            raise NotADirectoryError(
                f"Workspace is not a directory: {self.root}"
            )

    def resolve(self, target: str | Path) -> Path:
        """
        Resolve a target path safely.

        Existing paths are resolved normally.
        Non-existing paths are resolved from their parent.
        """
        raw = Path(target)

        if not raw.is_absolute():
            raw = self.root / raw

        try:
            return raw.resolve(strict=False)
        except OSError as exc:
            raise WorkspaceViolation(
                f"Unable to resolve path: {target}"
            ) from exc

    def is_inside(self, target: str | Path) -> bool:
        candidate = self.resolve(target)

        try:
            candidate.relative_to(self.root)
            return True
        except ValueError:
            return False

    def require_inside(self, target: str | Path) -> Path:
        candidate = self.resolve(target)

        if not self.is_inside(candidate):
            raise WorkspaceViolation(
                f"ACCESS DENIED: path outside workspace: {candidate}"
            )

        return candidate

    def require_existing_inside(self, target: str | Path) -> Path:
        candidate = self.require_inside(target)

        if not candidate.exists():
            raise FileNotFoundError(candidate)

        return candidate

    def require_file_inside(self, target: str | Path) -> Path:
        candidate = self.require_existing_inside(target)

        if not candidate.is_file():
            raise WorkspaceViolation(
                f"Expected file, got: {candidate}"
            )

        return candidate

    def require_directory_inside(self, target: str | Path) -> Path:
        candidate = self.require_existing_inside(target)

        if not candidate.is_dir():
            raise WorkspaceViolation(
                f"Expected directory, got: {candidate}"
            )

        return candidate


def main() -> int:
    # Test workspace:
    workspace = Path.cwd()
    guard = WorkspaceGuard(workspace)

    print(f"Workspace: {guard.root}")
    print()

    tests = [
        ".",
        "roles.json",
        "connections.json",
        "..",
        Path.home(),
    ]

    for target in tests:
        try:
            resolved = guard.resolve(target)
            allowed = guard.is_inside(target)

            print(
                f"{str(target):<30} "
                f"{'ALLOW' if allowed else 'DENY ':<6} "
                f"{resolved}"
            )
        except Exception as exc:
            print(f"{target}: ERROR - {exc}")

    print()
    print("Workspace Guard test completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())