from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


SCHEMA_VERSION = 1


class SandboxPolicyError(ValueError):
    """Base error for execution resource policy failures."""


class SandboxPolicySafetyStop(SandboxPolicyError):
    """Raised when requested resource authority cannot be proven safe."""


@dataclass(frozen=True)
class ExternalResource:
    path: str
    access: str = "read"
    label: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "access": self.access, "label": self.label}


class WorkspaceResourcePolicy:
    """Separate workspace, tool, and explicitly-authorized external resources.

    A tool installed outside the workspace is executable authority only. Its
    location does not become data authority over the rest of the filesystem.
    External data paths require an explicit access declaration.
    """

    _ACCESS_MODES = {"read", "write", "read_write"}

    def __init__(
        self,
        workspace_root: Path,
        *,
        allowed_tool_paths: Sequence[Path | str] = (),
        external_resources: Sequence[ExternalResource | Mapping[str, object]] = (),
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        if not self.workspace_root.exists() or not self.workspace_root.is_dir():
            raise SandboxPolicySafetyStop(
                f"Workspace root must be an existing directory: {self.workspace_root}"
            )

        self.allowed_tool_paths = frozenset(
            self._normalize_tool_path(item) for item in allowed_tool_paths
        )
        self.external_resources = tuple(
            self._normalize_external_resource(item) for item in external_resources
        )

    def validate_tool_executable(self, executable: Path | str) -> Path:
        candidate = Path(executable)
        if not candidate.is_absolute():
            raise SandboxPolicySafetyStop(
                f"Tool executable must use an explicit absolute path: {executable!r}"
            )
        resolved = candidate.resolve(strict=True)
        if resolved not in self.allowed_tool_paths:
            raise SandboxPolicySafetyStop(
                f"Tool executable is not explicitly allowlisted: {resolved}"
            )
        if not resolved.is_file():
            raise SandboxPolicySafetyStop(
                f"Tool executable is not a regular file: {resolved}"
            )
        return resolved

    def validate_workspace_path(self, path: Path | str) -> Path:
        raw = Path(path)
        candidate = raw if raw.is_absolute() else self.workspace_root / raw
        resolved = candidate.resolve(strict=False)
        self._assert_inside_workspace(resolved, str(path))
        self._reject_symlink_escape(resolved)
        return resolved

    def validate_external_path(self, path: Path | str, *, access: str) -> Path:
        access = access.strip().lower() if isinstance(access, str) else access
        if access not in self._ACCESS_MODES:
            raise SandboxPolicyError(f"Unsupported external access mode: {access!r}")

        candidate = Path(path).resolve(strict=False)
        for resource in self.external_resources:
            if access not in self._compatible_modes(resource.access, access):
                continue
            resource_root = Path(resource.path)
            try:
                candidate.relative_to(resource_root)
                return candidate
            except ValueError:
                continue

        raise SandboxPolicySafetyStop(
            f"External resource is not explicitly authorized for {access}: {candidate}"
        )

    def classify_path(self, path: Path | str) -> str:
        candidate = Path(path).resolve(strict=False)
        try:
            candidate.relative_to(self.workspace_root)
            return "workspace"
        except ValueError:
            pass

        for resource in self.external_resources:
            try:
                candidate.relative_to(Path(resource.path))
                return "external"
            except ValueError:
                continue
        return "unmanaged"

    def describe(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "workspace_root": str(self.workspace_root),
            "allowed_tool_paths": sorted(str(item) for item in self.allowed_tool_paths),
            "external_resources": [item.to_dict() for item in self.external_resources],
        }

    @staticmethod
    def _normalize_tool_path(value: Path | str) -> Path:
        candidate = Path(value)
        if not candidate.is_absolute():
            raise SandboxPolicySafetyStop(f"Tool path must be absolute: {value!r}")
        return candidate.resolve(strict=False)

    @classmethod
    def _normalize_external_resource(
        cls,
        value: ExternalResource | Mapping[str, object],
    ) -> ExternalResource:
        if isinstance(value, ExternalResource):
            resource = value
        elif isinstance(value, Mapping):
            raw_path = value.get("path")
            access = value.get("access", "read")
            label = value.get("label", "")
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise SandboxPolicyError("External resource path must be non-empty")
            if not isinstance(access, str) or not access.strip():
                raise SandboxPolicyError("External resource access must be non-empty")
            if not isinstance(label, str):
                raise SandboxPolicyError("External resource label must be a string")
            resource = ExternalResource(
                path=raw_path,
                access=access.strip().lower(),
                label=label,
            )
        else:
            raise SandboxPolicyError(
                "External resource must be a mapping or ExternalResource"
            )

        if resource.access not in cls._ACCESS_MODES:
            raise SandboxPolicyError(
                f"Unsupported external resource access mode: {resource.access!r}"
            )
        resource_path = Path(resource.path)
        if not resource_path.is_absolute():
            raise SandboxPolicySafetyStop(
                f"External resource must use an absolute path: {resource.path!r}"
            )

        return ExternalResource(
            path=str(resource_path.resolve(strict=False)),
            access=resource.access,
            label=resource.label,
        )

    @staticmethod
    def _compatible_modes(resource_access: str, requested_access: str) -> set[str]:
        if resource_access == "read_write":
            return {"read", "write", "read_write"}
        if resource_access == requested_access:
            return {requested_access}
        return set()

    def _assert_inside_workspace(self, candidate: Path, source: str) -> None:
        try:
            candidate.relative_to(self.workspace_root)
        except ValueError as exc:
            raise SandboxPolicySafetyStop(
                f"Path escapes active workspace: {source!r}"
            ) from exc

    def _reject_symlink_escape(self, candidate: Path) -> None:
        relative_parts = candidate.relative_to(self.workspace_root).parts
        current = self.workspace_root
        for part in relative_parts:
            current = current / part
            if current.is_symlink():
                raise SandboxPolicySafetyStop(
                    f"Symlink/junction path is not permitted: {candidate}"
                )
