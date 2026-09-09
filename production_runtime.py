from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from central_leader import CentralLeader
from connection_manager import sync_external_secret_sources
from durable_execution_state import DurableExecutionState
from execution_authorization import ExecutionAuthorizationBoundary
from independent_validation import IndependentValidator, ValidationHook
from leader_router import LeaderRouter
from orchestration import CanonicalOrchestrator, OrchestrationResult, ProjectUnderstandingAdapter, WorkerAdapter, default_validator_factory
from plan_decomposer import PlanDecomposer
from project_understanding_pipeline import ProjectUnderstandingPipeline
from startup_recovery import StartupRecovery, StartupRecoveryReport
from worker_dispatch import WorkerDispatcher
from worker_execution import CheckpointHook, WorkerExecutionBoundary
from worker_lease_recovery import WorkerLeaseRecovery
from worker_router import WorkerRouter


class ProductionRuntimeConfigurationError(ValueError):
    """Raised when the production runtime cannot be safely constructed."""


@dataclass(frozen=True)
class ProductionRuntimeConfig:
    workspace_root: Path
    max_tasks: int = 100
    worker_timeout_seconds: float = 300.0
    worker_max_output_chars: int = 20_000
    durable_state_path: Path | None = None

    def validate(self) -> None:
        root = self.workspace_root.resolve()
        if not root.exists() or not root.is_dir():
            raise ProductionRuntimeConfigurationError(f"Workspace root must be an existing directory: {root}")
        if not isinstance(self.max_tasks, int) or self.max_tasks < 1:
            raise ProductionRuntimeConfigurationError("max_tasks must be positive")
        if self.worker_timeout_seconds <= 0:
            raise ProductionRuntimeConfigurationError("worker_timeout_seconds must be positive")
        if not isinstance(self.worker_max_output_chars, int) or self.worker_max_output_chars < 256:
            raise ProductionRuntimeConfigurationError("worker_max_output_chars must be >= 256")
        if self.durable_state_path is not None and not isinstance(self.durable_state_path, Path):
            raise ProductionRuntimeConfigurationError("durable_state_path must be a Path when provided")


class ProductionRuntime:
    """Construct the canonical orchestrator from explicit production dependencies."""

    def __init__(self, config: ProductionRuntimeConfig, *, leader_transport: Callable[[Any], Any], worker_adapter: WorkerAdapter, checkpoint: CheckpointHook, leader_router: LeaderRouter, worker_router: WorkerRouter, understanding: ProjectUnderstandingAdapter | None = None, validator_factory: Callable[[ValidationHook], IndependentValidator] | None = None) -> None:
        config.validate()
        dependencies = {"leader_transport": leader_transport, "worker_adapter": worker_adapter, "checkpoint": checkpoint, "leader_router": leader_router, "worker_router": worker_router}
        missing = [name for name, value in dependencies.items() if value is None]
        if missing:
            raise ProductionRuntimeConfigurationError("Production runtime requires explicit dependencies: " + ", ".join(sorted(missing)))
        if not callable(leader_transport):
            raise ProductionRuntimeConfigurationError("leader_transport must be callable")
        if not callable(checkpoint):
            raise ProductionRuntimeConfigurationError("A worker checkpoint hook is required; execution cannot proceed without explicit checkpoint authority")

        self.secret_sync_report = sync_external_secret_sources()
        root = config.workspace_root.resolve()
        self.config = config
        self.leader_router = leader_router
        self.worker_router = worker_router
        self.understanding = understanding or ProjectUnderstandingPipeline(root)
        self.leader = CentralLeader(router=self.leader_router, transport=leader_transport)
        self.decomposer = PlanDecomposer(max_tasks=config.max_tasks)
        self.dispatcher = WorkerDispatcher(router=self.worker_router)
        self.worker_execution = WorkerExecutionBoundary(root, checkpoint=checkpoint, active_lease_lookup=lambda task_id: self.worker_router.active_leases().get(task_id), timeout_seconds=config.worker_timeout_seconds, max_output_chars=config.worker_max_output_chars)
        self.worker_adapter = worker_adapter
        self.validator_factory = validator_factory or default_validator_factory(root)
        self.authorization = ExecutionAuthorizationBoundary(root)
        state_path = (config.durable_state_path or (root / ".agent_runtime" / "execution_state.sqlite3")).resolve()
        self.durable_state = DurableExecutionState(state_path)
        self.worker_lease_recovery = WorkerLeaseRecovery(self.durable_state)
        self.startup_recovery = StartupRecovery(self.durable_state, root)
        self.startup_recovery_report: StartupRecoveryReport = self.startup_recovery.recover()
        self.orchestrator = CanonicalOrchestrator(root, understanding=self.understanding, leader=self.leader, decomposer=self.decomposer, dispatcher=self.dispatcher, worker_execution=self.worker_execution, worker_adapter=self.worker_adapter, validator_factory=self.validator_factory, authorization=self.authorization, durable_state=self.durable_state)

    def run(self, task_id: str) -> OrchestrationResult:
        return self.orchestrator.run(task_id)

    def close(self) -> None:
        self.durable_state.close()


def build_production_runtime(workspace_root: Path, *, leader_transport: Callable[[Any], Any], worker_adapter: WorkerAdapter, checkpoint: CheckpointHook, leader_router: LeaderRouter, worker_router: WorkerRouter, max_tasks: int = 100, worker_timeout_seconds: float = 300.0, worker_max_output_chars: int = 20_000, durable_state_path: Path | None = None) -> ProductionRuntime:
    """Build the canonical production runtime without hidden policy shortcuts."""
    return ProductionRuntime(ProductionRuntimeConfig(workspace_root=workspace_root, max_tasks=max_tasks, worker_timeout_seconds=worker_timeout_seconds, worker_max_output_chars=worker_max_output_chars, durable_state_path=durable_state_path), leader_transport=leader_transport, worker_adapter=worker_adapter, checkpoint=checkpoint, leader_router=leader_router, worker_router=worker_router)