from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Mapping, Any

def _require_string_sequence(value, field):
    if value is None:
        raise ValueError(f"TaskContract {field} must be a sequence")
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"TaskContract {field} must be a sequence of strings, got {type(value).__name__}")
    normalized = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"TaskContract {field} contains non-string: {type(item).__name__}")
        stripped = item.strip()
        if not stripped:
            raise ValueError(f"TaskContract {field} contains empty string")
        normalized.append(stripped)
    return tuple(dict.fromkeys(normalized))

@dataclass(frozen=True)
class TaskContract:
    goal: str
    constraints: tuple[str, ...]
    dependencies: tuple[str, ...]
    file_scope: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    required_work_products: tuple[str, ...]
    input_references: tuple[str, ...]
    validation_requirements: tuple[str, ...]
    capabilities: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "constraints": list(self.constraints),
            "dependencies": list(self.dependencies),
            "file_scope": list(self.file_scope),
            "acceptance_criteria": list(self.acceptance_criteria),
            "required_work_products": list(self.required_work_products),
            "input_references": list(self.input_references),
            "validation_requirements": list(self.validation_requirements),
            "capabilities": list(self.capabilities),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TaskContract":
        if not isinstance(d, dict):
            raise ValueError("TaskContract requires dict input")
        goal = d.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("TaskContract requires non-empty goal")
        return cls(
            goal=goal.strip(),
            constraints=_require_string_sequence(d.get("constraints"), "constraints"),
            dependencies=_require_string_sequence(d.get("dependencies"), "dependencies"),
            file_scope=_require_string_sequence(d.get("file_scope"), "file_scope"),
            acceptance_criteria=_require_string_sequence(d.get("acceptance_criteria"), "acceptance_criteria"),
            required_work_products=_require_string_sequence(d.get("required_work_products"), "required_work_products"),
            input_references=_require_string_sequence(d.get("input_references"), "input_references"),
            validation_requirements=_require_string_sequence(d.get("validation_requirements"), "validation_requirements"),
            capabilities=_require_string_sequence(d.get("capabilities"), "capabilities"),
        )
