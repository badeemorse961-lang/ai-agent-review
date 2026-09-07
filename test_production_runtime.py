from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from central_leader import LeaderLease
from production_runtime import (
    ProductionRuntime,
    ProductionRuntimeConfig,
    ProductionRuntimeConfigurationError,
    build_production_runtime,
)
from worker_router import WorkerLease


class StubLeaderRouter:
    def __init__(self) -> None:
        self.lease = LeaderLease(
            provider="openrouter",
            account_id="OR-01",
            model="leader-model",
            tier="ULTRA",
            task_id="TASK-1",
            leased_at=1.0,
        )

    def acquire(self, task_id: str) -> LeaderLease:
        self.lease = LeaderLease(
            provider=self.lease.provider,
            account_id=self.lease.account_id,
            model=self.lease.model,
            tier=self.lease.tier,
            task_id=task_id,
            leased_at=1.0,
        )
        return self.lease

    def snapshot(self) -> dict[str, Any]:
        return {"leases": {self.lease.task_id: self.lease.to_dict()}}

    def release(self, task_id: str) -> LeaderLease:
        assert task_id == self.lease.task_id
        return self.lease

    def fail_current_leader(self, task_id: str, reason: str) -> None:
        del task_id, reason


class StubWorkerRouter:
    def __init__(self) -> None:
        self.leases: dict[str, WorkerLease] = {}

    def active_leases(self) -> dict[str, WorkerLease]:
        return dict(self.leases)


class StubUnderstanding:
    def analyze(self) -> dict[str, Any]:
        return {"context": {}}


class StubWorkerAdapter:
    def prepare(self, task: dict[str, Any], assignment: dict[str, Any]) -> Any:
        del task, assignment
        raise AssertionError("worker adapter must not run during construction")

    def validate(self, request: Any, task: dict[str, Any], result: Any, spec: Any) -> dict[str, Any]:
        del request, task, result, spec
        return {"passed": True}


def checkpoint(request: Any) -> dict[str, Any]:
    return {"isolated": True, "checkpoint_id": str(request.task_id) + ":cp"}


def test_production_runtime_wires_canonical_boundaries(tmp_path: Path) -> None:
    runtime = ProductionRuntime(
        ProductionRuntimeConfig(workspace_root=tmp_path),
        leader_transport=lambda request: {"plan": {"goal": "x", "tasks": []}},
        worker_adapter=StubWorkerAdapter(),
        checkpoint=checkpoint,
        leader_router=StubLeaderRouter(),
        worker_router=StubWorkerRouter(),
        understanding=StubUnderstanding(),
    )

    assert isinstance(runtime, ProductionRuntime)
    assert runtime.leader.__class__.__name__ == "CentralLeader"
    assert runtime.decomposer.__class__.__name__ == "PlanDecomposer"
    assert runtime.dispatcher.__class__.__name__ == "WorkerDispatcher"
    assert runtime.worker_execution.__class__.__name__ == "WorkerExecutionBoundary"
    assert runtime.authorization.__class__.__name__ == "ExecutionAuthorizationBoundary"


def test_build_requires_explicit_worker_adapter(tmp_path: Path) -> None:
    with pytest.raises(ProductionRuntimeConfigurationError, match="WorkerAdapter"):
        build_production_runtime(
            tmp_path,
            leader_transport=lambda request: {"plan": {"goal": "x", "tasks": []}},
            worker_adapter=None,  # type: ignore[arg-type]
            checkpoint=checkpoint,
        )


def test_build_requires_explicit_checkpoint(tmp_path: Path) -> None:
    with pytest.raises(ProductionRuntimeConfigurationError, match="checkpoint"):
        build_production_runtime(
            tmp_path,
            leader_transport=lambda request: {"plan": {"goal": "x", "tasks": []}},
            worker_adapter=StubWorkerAdapter(),
            checkpoint=None,  # type: ignore[arg-type]
        )


def test_invalid_runtime_configuration_stops_early(tmp_path: Path) -> None:
    with pytest.raises(ProductionRuntimeConfigurationError, match="max_tasks"):
        ProductionRuntime(
            ProductionRuntimeConfig(workspace_root=tmp_path, max_tasks=0),
            leader_transport=lambda request: {},
            worker_adapter=StubWorkerAdapter(),
            checkpoint=checkpoint,
            leader_router=StubLeaderRouter(),
            worker_router=StubWorkerRouter(),
            understanding=StubUnderstanding(),
        )
