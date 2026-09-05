from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from worker_router import ConfigurationError, LeaseError, NoWorkerAvailable, WorkerRouter


SCHEMA_VERSION = 1


class WorkerDispatchError(ValueError):
    """Base error raised by the worker dispatch boundary."""


class WorkerDispatchSafetyStop(WorkerDispatchError):
    """Raised when a plan is not safe for worker assignment."""


@dataclass(frozen=True)
class WorkerAssignment:
    task_id: str
    role: str
    worker_id: str
    standby: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "role": self.role,
            "worker_id": self.worker_id,
            "standby": self.standby,
        }


class WorkerDispatcher:
    """Guarded assignment boundary between validated plans and worker leases.

    No provider calls, secret loading, filesystem mutation, or command execution
    occur here. The dispatcher only validates task metadata and acquires leases
    from the registry-driven ``WorkerRouter``.
    """

    def __init__(self, router: Optional[WorkerRouter] = None) -> None:
        self.router = router or WorkerRouter()

    def assign_plan(self, plan: Mapping[str, Any]) -> list[WorkerAssignment]:
        self._validate_plan(plan)
        tasks = plan.get("tasks")
        assert isinstance(tasks, list)

        assignments: list[WorkerAssignment] = []
        acquired: list[str] = []
        try:
            for task in self._topological_tasks(tasks):
                task_id = str(task["task_id"])
                role = str(task["role"])
                try:
                    lease = self.router.acquire(role, task_id)
                except (NoWorkerAvailable, LeaseError, ConfigurationError) as exc:
                    raise WorkerDispatchError(
                        f"Unable to assign task {task_id!r}: {exc}"
                    ) from exc
                acquired.append(task_id)
                assignments.append(
                    WorkerAssignment(
                        task_id=task_id,
                        role=role,
                        worker_id=lease.worker_id,
                        standby=lease.standby,
                    )
                )
        except Exception:
            for task_id in reversed(acquired):
                try:
                    self.router.release(task_id)
                except Exception:
                    pass
            raise

        return assignments

    def release_all(self, assignments: Iterable[WorkerAssignment]) -> None:
        for assignment in assignments:
            try:
                self.router.release(assignment.task_id)
            except LeaseError:
                continue

    def _validate_plan(self, plan: Mapping[str, Any]) -> None:
        if not isinstance(plan, Mapping):
            raise WorkerDispatchSafetyStop("Worker dispatch requires a plan mapping")

        authority = plan.get("authority")
        if isinstance(authority, Mapping):
            if authority.get("execution_authorized", False) is not False:
                raise WorkerDispatchSafetyStop(
                    "Worker assignment cannot receive execution authority from the plan"
                )
            if authority.get("mutation_allowed", False) is not False:
                raise WorkerDispatchSafetyStop(
                    "Worker assignment cannot receive mutation authority from the plan"
                )
            if authority.get("worker_assignment_authorized", False) is not False:
                raise WorkerDispatchSafetyStop(
                    "Worker assignment must remain locally controlled"
                )
            if authority.get("model_output_trusted", False) is not False:
                raise WorkerDispatchSafetyStop(
                    "Model output cannot be trusted for worker assignment"
                )

        validation = plan.get("validation")
        if not isinstance(validation, Mapping):
            raise WorkerDispatchSafetyStop("Worker dispatch requires validation metadata")
        for key in ("dag_valid", "roles_valid", "dependencies_valid"):
            if validation.get(key) is not True:
                raise WorkerDispatchSafetyStop(
                    f"Validated plan is missing positive {key} proof"
                )

        tasks = plan.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            raise WorkerDispatchSafetyStop("Worker dispatch requires a non-empty task list")

        configured_roles = {
            str(role)
            for role, pool in self.router.worker_pools.items()
            if isinstance(role, str) and isinstance(pool, list) and pool
        }

        seen: set[str] = set()
        for task in tasks:
            if not isinstance(task, Mapping):
                raise WorkerDispatchSafetyStop("Every plan task must be an object")
            task_id = task.get("task_id")
            role = task.get("role")
            acceptance = task.get("acceptance_criteria")
            if not isinstance(task_id, str) or not task_id.strip():
                raise WorkerDispatchSafetyStop("Every task requires a non-empty task_id")
            if task_id in seen:
                raise WorkerDispatchSafetyStop(f"Duplicate task_id: {task_id}")
            seen.add(task_id)
            if not isinstance(role, str) or role not in configured_roles:
                raise WorkerDispatchSafetyStop(
                    f"Task {task_id!r} has an unavailable worker role: {role!r}"
                )
            if not isinstance(acceptance, list) or not acceptance or not all(
                isinstance(item, str) and item.strip() for item in acceptance
            ):
                raise WorkerDispatchSafetyStop(
                    f"Task {task_id!r} requires non-empty acceptance criteria"
                )

    @staticmethod
    def _topological_tasks(tasks: list[Any]) -> list[Mapping[str, Any]]:
        by_id = {str(task["task_id"]): task for task in tasks if isinstance(task, Mapping)}
        indegree = {task_id: 0 for task_id in by_id}
        outgoing: dict[str, list[str]] = {task_id: [] for task_id in by_id}

        for task_id, task in by_id.items():
            dependencies = task.get("depends_on", [])
            if not isinstance(dependencies, list):
                raise WorkerDispatchSafetyStop(
                    f"Task {task_id!r} dependencies must be a list"
                )
            for dependency in dependencies:
                dependency_id = str(dependency)
                if dependency_id not in by_id:
                    raise WorkerDispatchSafetyStop(
                        f"Task {task_id!r} references unknown dependency {dependency_id!r}"
                    )
                indegree[task_id] += 1
                outgoing[dependency_id].append(task_id)

        ready = sorted(task_id for task_id, value in indegree.items() if value == 0)
        ordered_ids: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered_ids.append(current)
            for dependent in sorted(outgoing[current]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
                    ready.sort()

        if len(ordered_ids) != len(by_id):
            raise WorkerDispatchSafetyStop("Plan dependency graph contains a cycle")

        return [by_id[task_id] for task_id in ordered_ids]


def dispatch_plan(
    plan: Mapping[str, Any],
    *,
    router: Optional[WorkerRouter] = None,
) -> list[WorkerAssignment]:
    """Functional entry point for the worker assignment boundary."""
    return WorkerDispatcher(router=router).assign_plan(plan)


if __name__ == "__main__":
    print("Worker dispatch boundary ready.")
