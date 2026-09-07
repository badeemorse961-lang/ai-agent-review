from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from central_leader import CentralLeader
from execution_authorization import ExecutionAuthorizationBoundary
from independent_validation import IndependentValidator, ValidationHook
from orchestration import (
    CanonicalOrchestrator,
    OrchestrationResult,
    ProjectUnderstandingAdapter,
    WorkerAdapter,
    default_validator_factory,
)
from plan_decomposer import PlanDecomposer
from project_understanding_pipeline import ProjectUnderstandingPipeline
from worker_dispatch import WorkerDispatcher
from worker_execution import WorkerExecutionBoundary
from worker_router import WorkerRouter
from leader_router import LeaderRouter


class ProductionRuntimeConfigurationError(ValueError):
    """Raised when the production runtime cannot be safely constructed."""


@dataclass(frozen=True)
class ProductionRuntimeConfig:
    workspace_root: Path
    max_tasks: int = 100
    worker_timeout_seconds: float = 300.0
    worker_max_output_chars: int = 20_000

    def validate(self) -> None:
        root = self.workspace_root.resolve()
        if not root.exists() or not root.is_dir():
            raise ProductionRuntimeConfigurationError(
                f"Workspace root must be an existing directory: {root}"
            )
        if not isinstance(self.max_tasks, int) or self.max_tasks < 1:
            raise ProductionRuntimeConfigurationError("max_tasks must be positive")
        if self.worker_timeout_seconds <= 0:
            raise ProductionRuntimeConfigurationError(
                "worker_timeout_seconds must be positive"
            )
        if (
            not isinstance(self.worker_max_output_chars, int)
            or self.worker_max_output_chars < 256
        ):
            raise ProductionRuntimeConfigurationError(
                "worker_max_output_chars must be >= 256"
            )


class ProductionRuntime:
    """Construct the canonical orchestrator from real repository boundaries.

    Provider transport and the concrete WorkerAdapter are explicit dependencies.
    The runtime never invents worker commands, mutation targets, or execution
    authority when those adapters are not configured.
    """

    def __init__(
        self,
        config: ProductionRuntimeConfig,
        *,
        leader_transport: Callable[[Any], Any],
        worker_adapter: WorkerAdapter,
        leader_router: LeaderRouter | None = None,
        worker_router: WorkerRouter | None = None,
        understanding: ProjectUnderstandingAdapter | None = None,
        validator_factory: Callable[[ValidationHook], IndependentValidator] | None = None,
    ) -> None:
        config.validate()
        if not callable(leader_transport):
            raise ProductionRuntimeConfigurationError(
                "leader_transport must be callable"
            )
        if worker_adapter is None:
            raise ProductionRuntimeConfigurationError(
                "A concrete WorkerAdapter is required; worker behavior must not be invented by the runtime"
            )

        root = config.workspace_root.resolve()
        self.config = config
        self.leader_router = leader_router or LeaderRouter()
        self.worker_router = worker_router or WorkerRouter()
        self.understanding = understanding or ProjectUnderstandingPipeline(root)
        self.leader = CentralLeader(
            router=self.leader_router,
            transport=leader_transport,
        )
        self.decomposer = PlanDecomposer(max_tasks=config.max_tasks)
        self.dispatcher = WorkerDispatcher(router=self.worker_router)
        self.worker_execution = WorkerExecutionBoundary(
            root,
            active_lease_lookup=lambda task_id: self.worker_router.active_leases().get(task_id),
            timeout_seconds=config.worker_timeout_seconds,
            max_output_chars=config.worker_max_output_chars,
        )
        self.worker_adapter = worker_adapter
        self.validator_factory = validator_factory or default_validator_factory(root)
        self.authorization = ExecutionAuthorizationBoundary(root)
        self.orchestrator = CanonicalOrchestrator(
            root,
            understanding=self.understanding,
            leader=self.leader,
            decomposer=self.decomposer,
            dispatcher=self.dispatcher,
            worker_execution=self.worker_execution,
            worker_adapter=self.worker_adapter,
            validator_factory=self.validator_factory,
            authorization=self.authorization,
        )

    def run(self, task_id: str) -> OrchestrationResult:
        return self.orchestrator.run(task_id)


def build_production_runtime(
    workspace_root: Path,
    *,
    leader_transport: Callable[[Any], Any],
    worker_adapter: WorkerAdapter,
    max_tasks: int = 100,
    worker_timeout_seconds: float = 300.0,
    worker_max_output_chars: int = 20_000,
) -> ProductionRuntime:
    """Build the canonical production runtime without hidden policy shortcuts."""
    return ProductionRuntime(
        ProductionRuntimeConfig(
            workspace_root=workspace_root,
            max_tasks=max_tasks,
            worker_timeout_seconds=worker_timeout_seconds,
            worker_max_output_chars=worker_max_output_chars,
        ),
        leader_transport=leader_transport,
        worker_adapter=worker_adapter,
    )
