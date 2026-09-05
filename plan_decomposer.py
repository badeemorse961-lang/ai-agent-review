from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from config_registry import RegistryError, validate_registry


SCHEMA_VERSION = 1
DEFAULT_MAX_TASKS = 100


class PlanDecompositionError(ValueError):
    """Raised when leader output cannot be converted into a safe task plan."""


@dataclass(frozen=True)
class PlanTask:
    task_id: str
    role: str
    objective: str
    depends_on: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    priority: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "role": self.role,
            "objective": self.objective,
            "depends_on": list(self.depends_on),
            "acceptance_criteria": list(self.acceptance_criteria),
            "priority": self.priority,
        }


class PlanDecomposer:
    """Validate and normalize untrusted leader output into a task DAG.

    The decomposer is deliberately provider-independent and read-only. It does
    not execute tasks, mutate files, lease workers, or grant execution
    authority. Worker roles are read dynamically from the authoritative
    ``config/registry.json`` registry, so adding or removing pool entries does
    not require a code change.
    """

    def __init__(
        self,
        *,
        max_tasks: int = DEFAULT_MAX_TASKS,
        allowed_roles: Sequence[str] | None = None,
    ) -> None:
        if not isinstance(max_tasks, int) or max_tasks < 1:
            raise PlanDecompositionError("max_tasks must be a positive integer")

        self.max_tasks = max_tasks
        self.allowed_roles = set(allowed_roles) if allowed_roles is not None else self._registry_roles()
        if not self.allowed_roles:
            raise PlanDecompositionError("No worker roles are configured")

    def decompose(
        self,
        leader_output: Any,
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self._extract_payload(leader_output)
        plan = payload.get("plan", payload)
        if not isinstance(plan, Mapping):
            raise PlanDecompositionError("Leader output must contain a plan object")

        self._validate_context(context)

        goal = self._required_text(plan, "goal")
        raw_tasks = plan.get("tasks") or plan.get("steps")
        if not isinstance(raw_tasks, list):
            raise PlanDecompositionError("Plan must contain a tasks or steps list")
        if len(raw_tasks) > self.max_tasks:
            raise PlanDecompositionError(
                f"Plan contains {len(raw_tasks)} tasks; max_tasks is {self.max_tasks}"
            )

        tasks = [self._task(item, index) for index, item in enumerate(raw_tasks, 1)]
        self._validate_unique_ids(tasks)
        self._validate_dependencies(tasks)

        return {
            "schema_version": SCHEMA_VERSION,
            "plan_kind": "validated_task_plan",
            "goal": goal,
            "tasks": [task.to_dict() for task in tasks],
            "authority": {
                "execution_authorized": False,
                "mutation_allowed": False,
                "worker_assignment_authorized": False,
                "model_output_trusted": False,
            },
            "validation": {
                "task_count": len(tasks),
                "dag_valid": True,
                "roles_valid": True,
                "dependencies_valid": True,
            },
        }

    @staticmethod
    def _extract_payload(value: Any) -> Mapping[str, Any]:
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str):
            import json

            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise PlanDecompositionError("Leader output string is not valid JSON") from exc
            if isinstance(parsed, Mapping):
                return parsed
        raise PlanDecompositionError("Leader output must be a mapping or JSON object string")

    @staticmethod
    def _validate_context(context: Mapping[str, Any] | None) -> None:
        if context is None:
            return
        if not isinstance(context, Mapping):
            raise PlanDecompositionError("Planning context must be a mapping")

        authority = context.get("authority")
        if isinstance(authority, Mapping):
            if authority.get("execution_authorized") is not False:
                raise PlanDecompositionError("Planning context cannot authorize execution")
            if authority.get("mutation_allowed") is not False:
                raise PlanDecompositionError("Planning context cannot permit mutation")

    @staticmethod
    def _required_text(value: Mapping[str, Any], key: str) -> str:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise PlanDecompositionError(f"Plan field {key!r} must be a non-empty string")
        return item.strip()

    def _task(self, value: Any, index: int) -> PlanTask:
        if not isinstance(value, Mapping):
            raise PlanDecompositionError(f"Task {index} must be an object")

        task_id = self._required_text(value, "task_id")
        role = self._required_text(value, "role")
        objective = self._required_text(value, "objective")

        if role not in self.allowed_roles:
            raise PlanDecompositionError(
                f"Task {task_id!r} uses unconfigured worker role: {role!r}"
            )

        depends_on = self._string_list(value.get("depends_on", []), f"{task_id}.depends_on")
        criteria = self._string_list(
            value.get("acceptance_criteria", []),
            f"{task_id}.acceptance_criteria",
        )
        if not criteria:
            raise PlanDecompositionError(f"Task {task_id!r} must include acceptance criteria")

        priority = value.get("priority", 50)
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise PlanDecompositionError(f"Task {task_id!r} priority must be an integer")
        if not 0 <= priority <= 100:
            raise PlanDecompositionError(f"Task {task_id!r} priority must be between 0 and 100")

        return PlanTask(
            task_id=task_id,
            role=role,
            objective=objective,
            depends_on=tuple(dict.fromkeys(depends_on)),
            acceptance_criteria=tuple(dict.fromkeys(criteria)),
            priority=priority,
        )

    @staticmethod
    def _string_list(value: Any, field: str) -> list[str]:
        if not isinstance(value, list):
            raise PlanDecompositionError(f"{field} must be a list")
        result: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise PlanDecompositionError(f"{field} contains a non-empty string violation")
            result.append(item.strip())
        return result

    @staticmethod
    def _validate_unique_ids(tasks: Sequence[PlanTask]) -> None:
        seen: set[str] = set()
        for task in tasks:
            if task.task_id in seen:
                raise PlanDecompositionError(f"Duplicate task_id: {task.task_id}")
            seen.add(task.task_id)

    @staticmethod
    def _validate_dependencies(tasks: Sequence[PlanTask]) -> None:
        ids = {task.task_id for task in tasks}
        edges = {task.task_id: set(task.depends_on) for task in tasks}

        for task in tasks:
            missing = edges[task.task_id] - ids
            if missing:
                raise PlanDecompositionError(
                    f"Task {task.task_id!r} depends on unknown tasks: {sorted(missing)}"
                )
            if task.task_id in edges[task.task_id]:
                raise PlanDecompositionError(f"Task {task.task_id!r} cannot depend on itself")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise PlanDecompositionError("Task dependencies contain a cycle")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in sorted(edges[task_id]):
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in sorted(ids):
            visit(task_id)

    @staticmethod
    def _registry_roles() -> set[str]:
        try:
            registry = validate_registry()
        except RegistryError as exc:
            raise PlanDecompositionError(f"Invalid worker registry: {exc}") from exc

        architecture = registry.get("architecture")
        workers = architecture.get("workers") if isinstance(architecture, Mapping) else None
        roles = workers.get("roles") if isinstance(workers, Mapping) else None
        if not isinstance(roles, Mapping):
            raise PlanDecompositionError("Registry does not define worker roles")
        return {
            str(role)
            for role, pool in roles.items()
            if isinstance(role, str) and isinstance(pool, list) and pool
        }


def decompose_plan(
    leader_output: Any,
    *,
    context: Mapping[str, Any] | None = None,
    max_tasks: int = DEFAULT_MAX_TASKS,
    allowed_roles: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Functional entry point for safe plan decomposition."""
    return PlanDecomposer(
        max_tasks=max_tasks,
        allowed_roles=allowed_roles,
    ).decompose(leader_output, context=context)


if __name__ == "__main__":
    print("Plan decomposition boundary ready.")
