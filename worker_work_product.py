from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from execution_gate import FileChange

SCHEMA_VERSION = 1
ALLOWED_STATUSES = frozenset({"READY", "NO_MUTATION", "FAILED"})


class WorkerWorkProductError(ValueError):
    """Raised when a worker work-product violates the canonical contract."""


@dataclass(frozen=True)
class WorkerWorkProduct:
    """Canonical typed worker output; it grants no execution or mutation authority."""

    task_id: str
    worker_id: str
    role: str
    command: tuple[str, ...]
    targets: tuple[str, ...]
    changed_targets: tuple[str, ...]
    changes: tuple[FileChange, ...]
    validation_evidence: Mapping[str, Any]
    status: str = "READY"
    failure: Mapping[str, Any] | None = None
    external_reads: tuple[str, ...] = ()
    external_writes: tuple[str, ...] = ()

    def validate(self, *, task_id: str, worker_id: str, role: str) -> None:
        self._validate_string("task_id", self.task_id)
        self._validate_string("worker_id", self.worker_id)
        self._validate_string("role", self.role)
        for name, expected in (("task_id", task_id), ("worker_id", worker_id), ("role", role)):
            self._validate_string(f"expected_{name}", expected)
        if self.task_id != task_id:
            raise WorkerWorkProductError("Worker work-product task identity mismatch")
        if self.worker_id != worker_id:
            raise WorkerWorkProductError("Worker work-product worker identity mismatch")
        if self.role != role:
            raise WorkerWorkProductError("Worker work-product role mismatch")
        if not self.command or any(not isinstance(item, str) or not item.strip() for item in self.command):
            raise WorkerWorkProductError("Worker work-product command must be non-empty strings")
        self._validate_paths("targets", self.targets)
        self._validate_paths("changed_targets", self.changed_targets)
        self._validate_paths("external_reads", self.external_reads)
        self._validate_paths("external_writes", self.external_writes)
        if any(not isinstance(change, FileChange) for change in self.changes):
            raise WorkerWorkProductError("changes must contain only FileChange records")
        if any(not isinstance(change.path, str) or not change.path.strip() for change in self.changes):
            raise WorkerWorkProductError("FileChange paths must be non-empty strings")
        if self.changes and {change.path for change in self.changes} != set(self.changed_targets):
            raise WorkerWorkProductError("FileChange paths must exactly match changed_targets")
        if not self.changes and self.changed_targets:
            raise WorkerWorkProductError("changed_targets cannot exist without FileChange records")
        if not isinstance(self.validation_evidence, Mapping):
            raise WorkerWorkProductError("validation_evidence must be an object")
        if self.status not in ALLOWED_STATUSES:
            raise WorkerWorkProductError(f"Unsupported worker work-product status: {self.status!r}")
        if self.status == "FAILED" and not isinstance(self.failure, Mapping):
            raise WorkerWorkProductError("FAILED worker work-products require failure information")
        if self.status != "FAILED" and self.failure is not None:
            raise WorkerWorkProductError("failure is only allowed for FAILED work-products")

    def to_dict(self) -> dict[str, Any]:
        self.validate(task_id=self.task_id, worker_id=self.worker_id, role=self.role)
        return {
            "schema_version": SCHEMA_VERSION,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "role": self.role,
            "action": {
                "command": list(self.command),
                "targets": list(self.targets),
                "external_reads": list(self.external_reads),
                "external_writes": list(self.external_writes),
            },
            "mutation": {
                "changed_targets": list(self.changed_targets),
                "changes": [
                    {"path": c.path, "old_text": c.old_text, "new_text": c.new_text}
                    for c in self.changes
                ],
            },
            "validation_evidence": dict(self.validation_evidence),
            "status": self.status,
            "failure": dict(self.failure) if self.failure is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkerWorkProduct":
        if not isinstance(payload, Mapping):
            raise WorkerWorkProductError("Worker work-product must be an object")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise WorkerWorkProductError("Unsupported worker work-product schema_version")
        for key in ("task_id", "worker_id", "role", "status"):
            if not isinstance(payload.get(key), str):
                raise WorkerWorkProductError(f"{key} must be a string")
        action = payload.get("action")
        mutation = payload.get("mutation")
        evidence = payload.get("validation_evidence")
        if not isinstance(action, Mapping) or not isinstance(mutation, Mapping):
            raise WorkerWorkProductError("Worker work-product requires action and mutation objects")
        if not isinstance(evidence, Mapping):
            raise WorkerWorkProductError("validation_evidence must be an object")

        def strings(value: Any, name: str) -> tuple[str, ...]:
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise WorkerWorkProductError(f"{name} must be a list of strings")
            return tuple(value)

        changes_raw = mutation.get("changes")
        if not isinstance(changes_raw, list):
            raise WorkerWorkProductError("mutation.changes must be a list")
        changes: list[FileChange] = []
        for item in changes_raw:
            if not isinstance(item, Mapping):
                raise WorkerWorkProductError("Every mutation change must be an object")
            if not all(isinstance(item.get(key), str) for key in ("path", "old_text", "new_text")):
                raise WorkerWorkProductError("FileChange fields must be strings")
            changes.append(FileChange(item["path"], item["old_text"], item["new_text"]))

        failure = payload.get("failure")
        if failure is not None and not isinstance(failure, Mapping):
            raise WorkerWorkProductError("failure must be an object or null")
        product = cls(
            task_id=payload["task_id"],
            worker_id=payload["worker_id"],
            role=payload["role"],
            command=strings(action.get("command"), "action.command"),
            targets=strings(action.get("targets"), "action.targets"),
            changed_targets=strings(mutation.get("changed_targets"), "mutation.changed_targets"),
            changes=tuple(changes),
            validation_evidence=evidence,
            status=payload["status"],
            failure=failure,
            external_reads=strings(action.get("external_reads", []), "action.external_reads"),
            external_writes=strings(action.get("external_writes", []), "action.external_writes"),
        )
        product.validate(task_id=product.task_id, worker_id=product.worker_id, role=product.role)
        return product

    def to_execution_spec(self) -> Any:
        from orchestration import WorkerExecutionSpec
        self.validate(task_id=self.task_id, worker_id=self.worker_id, role=self.role)
        return WorkerExecutionSpec(
            command=self.command,
            targets=self.targets,
            changed_targets=self.changed_targets,
            changes=self.changes,
            external_reads=self.external_reads,
            external_writes=self.external_writes,
        )

    @staticmethod
    def _validate_string(name: str, value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            raise WorkerWorkProductError(f"{name} must be a non-empty string")

    @staticmethod
    def _validate_paths(name: str, values: tuple[str, ...]) -> None:
        if not isinstance(values, tuple) or any(not isinstance(item, str) or not item.strip() for item in values):
            raise WorkerWorkProductError(f"{name} must be a tuple of non-empty strings")
        if len(set(values)) != len(values):
            raise WorkerWorkProductError(f"{name} must not contain duplicate paths")
