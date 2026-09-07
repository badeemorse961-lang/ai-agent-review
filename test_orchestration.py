from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pytest

import execution_gate as execution_gate_module
from central_leader import CentralLeader, LeaderLease, LeaderPlanningSafetyStop
from execution_authorization import ExecutionAuthorizationBoundary, ExecutionAuthorizationSafetyStop
from execution_gate import FileChange
from independent_validation import IndependentValidationSafetyStop
from orchestration import (
    CanonicalOrchestrator,
    OrchestrationSafetyStop,
    WorkerExecutionSpec,
    default_validator_factory,
)
from plan_decomposer import PlanDecomposer
from worker_dispatch import WorkerDispatcher
from worker_execution import WorkerExecutionBoundary, WorkerExecutionSafetyStop
from worker_router import WorkerLease


class StubUnderstanding:
    def __init__(self, context: Mapping[str, Any]) -> None:
        self.context = dict(context)
        self.calls = 0

    def analyze(self) -> Mapping[str, Any]:
        self.calls += 1
        return {"context": dict(self.context)}


class StubLeaderRouter:
    def __init__(self) -> None:
        self.leases: dict[str, LeaderLease] = {}
        self.released: list[str] = []

    def acquire(self, task_id: str) -> LeaderLease:
        lease = LeaderLease("openrouter", "OR-TEST", "leader-model", "ULTRA", task_id, 1.0)
        self.leases[task_id] = lease
        return lease

    def snapshot(self) -> dict[str, Any]:
        return {"leases": {key: value.to_dict() for key, value in self.leases.items()}}

    def release(self, task_id: str) -> LeaderLease:
        lease = self.leases.pop(task_id)
        self.released.append(task_id)
        return lease

    def fail_current_leader(self, task_id: str, reason: str) -> None:
        del reason
        self.leases.pop(task_id, None)


class StubWorkerRouter:
    def __init__(self, worker_ids: tuple[str, ...] = ("W-1", "W-2")) -> None:
        self.worker_pools = {"coder": list(worker_ids)}
        self.leases: dict[str, WorkerLease] = {}
        self.released: list[str] = []

    def acquire(self, role: str, task_id: str) -> WorkerLease:
        for worker_id in self.worker_pools[role]:
            if all(lease.worker_id != worker_id for lease in self.leases.values()):
                lease = WorkerLease(worker_id, role, task_id, 1.0, False)
                self.leases[task_id] = lease
                return lease
        raise RuntimeError("no worker available")

    def active_leases(self) -> dict[str, WorkerLease]:
        return dict(self.leases)

    def release(self, task_id: str) -> WorkerLease:
        lease = self.leases.pop(task_id)
        self.released.append(task_id)
        return lease


class StubWorkerAdapter:
    def __init__(
        self,
        *,
        changes: bool = True,
        validation: Mapping[str, Any] | None = None,
    ) -> None:
        self.changes = changes
        self.validation = dict(validation or {"passed": True})
        self.prepared: list[str] = []
        self.validated: list[str] = []

    def prepare(
        self,
        task: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> WorkerExecutionSpec:
        del assignment
        task_id = str(task["task_id"])
        self.prepared.append(task_id)
        if self.changes:
            return WorkerExecutionSpec(
                command=("pytest", "-q", "test_target.py"),
                targets=("test_target.py",),
                changed_targets=("target.txt",),
                changes=(
                    FileChange(
                        "target.txt",
                        'VALUE = "before"',
                        'VALUE = "after"',
                    ),
                ),
            )
        return WorkerExecutionSpec(
            command=("pytest", "-q", "test_target.py"),
            targets=("test_target.py",),
            changed_targets=(),
            changes=(),
        )

    def validate(
        self,
        request: Any,
        task: Mapping[str, Any],
        result: Any,
        spec: WorkerExecutionSpec,
    ) -> Mapping[str, Any]:
        del request, result, spec
        self.validated.append(str(task["task_id"]))
        return dict(self.validation)


class StubAuthorization:
    def __init__(self) -> None:
        self.calls = 0

    def apply(
        self,
        verdict: Any,
        *,
        checkpoint: Mapping[str, Any],
        changes: Any,
    ) -> Mapping[str, Any]:
        self.calls += 1
        return {
            "status": "APPROVED",
            "authorization": {
                "task_id": verdict.task_id,
                "worker_id": verdict.worker_id,
                "authorized": True,
                "checkpoint_id": checkpoint["checkpoint_id"],
                "changed_targets": [change.path for change in changes],
            },
        }


def context(*, state: str = "BUILD", autonomous: bool = True) -> dict[str, Any]:
    return {
        "authority": {
            "execution_authorized": False,
            "mutation_allowed": False,
            "source_contents_included": False,
        },
        "project": {"state": state, "autonomous_start_allowed": autonomous},
    }


def workspace(tmp_path: Path) -> Path:
    (tmp_path / "target.txt").write_text('VALUE = "before"', encoding="utf-8")
    (tmp_path / "test_target.py").write_text(
        "from pathlib import Path\n\n"
        "def test_target_value():\n"
        "    assert Path('target.txt').read_text(encoding='utf-8') == 'VALUE = \\\"after\\\"'\n",
        encoding="utf-8",
    )
    return tmp_path


def make_orchestrator(
    root: Path,
    *,
    understanding: StubUnderstanding | None = None,
    worker_router: StubWorkerRouter | None = None,
    worker_adapter: StubWorkerAdapter | None = None,
    executor: Any | None = None,
    checkpoint: Any | None = None,
    authorization: Any | None = None,
    max_output_chars: int = 20_000,
):
    leader_router = StubLeaderRouter()
    worker_router = worker_router or StubWorkerRouter()
    worker_adapter = worker_adapter or StubWorkerAdapter()
    understanding = understanding or StubUnderstanding(context())

    def default_executor(request: Any) -> tuple[int, str, str, bool]:
        del request
        return 0, "worker ok", "", False

    def active_lease(task_id: str) -> Any:
        return worker_router.active_leases().get(task_id)

    worker_execution = WorkerExecutionBoundary(
        root,
        executor=executor or default_executor,
        checkpoint=checkpoint
        or (lambda request: {
            "isolated": True,
            "checkpoint_id": request.task_id + ":cp",
        }),
        active_lease_lookup=active_lease,
        max_output_chars=max_output_chars,
    )
    authorization = authorization or StubAuthorization()
    leader = CentralLeader(
        router=leader_router,
        transport=lambda request: {
            "plan": {
                "goal": "update target",
                "tasks": [{
                    "task_id": request.task_id + ":1",
                    "role": "coder",
                    "objective": "make deterministic change",
                    "depends_on": [],
                    "acceptance_criteria": ["tests pass"],
                }],
            }
        },
    )
    orchestrator = CanonicalOrchestrator(
        root,
        understanding=understanding,
        leader=leader,
        decomposer=PlanDecomposer(allowed_roles=["coder"]),
        dispatcher=WorkerDispatcher(router=worker_router),
        worker_execution=worker_execution,
        worker_adapter=worker_adapter,
        validator_factory=default_validator_factory(root),
        authorization=authorization,
    )
    return orchestrator, leader_router, worker_router, worker_adapter, authorization


def isolate_gate_files(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(execution_gate_module, "STATE_FILE", root / "execution_gate_state.json")
    monkeypatch.setattr(execution_gate_module, "CHECKPOINT_ROOT", root / ".agent_gate_checkpoints")


def test_full_mutating_flow_uses_real_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = workspace(tmp_path)
    isolate_gate_files(monkeypatch, root)
    orchestrator, leader_router, worker_router, adapter, _ = make_orchestrator(root)
    orchestrator.authorization = ExecutionAuthorizationBoundary(root)

    result = orchestrator.run("TASK-1")

    assert result.status == "APPROVED"
    assert result.task_records[0].transaction["status"] == "APPROVED"
    assert result.task_records[0].work_product.status == "SUCCEEDED"
    assert result.task_records[0].work_product.task_id == "TASK-1:1"
    assert result.task_records[0].work_product.worker_id == "W-1"
    assert result.task_records[0].work_product.changed_targets == ("target.txt",)
    assert result.task_records[0].work_product.validation_evidence["checkpoint_id"] == "TASK-1:1:cp"
    assert (root / "target.txt").read_text(encoding="utf-8") == 'VALUE = "after"'
    assert adapter.prepared == ["TASK-1:1"]
    assert adapter.validated == ["TASK-1:1"]
    assert leader_router.released == ["TASK-1"]
    assert worker_router.released == ["TASK-1:1"]


def test_unknown_state_stops_before_leader(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    understanding = StubUnderstanding(context(state="UNKNOWN"))
    orchestrator, leader_router, worker_router, _, _ = make_orchestrator(
        root,
        understanding=understanding,
    )

    with pytest.raises(LeaderPlanningSafetyStop):
        orchestrator.run("TASK-UNKNOWN")

    assert understanding.calls == 1
    assert leader_router.leases == {}
    assert worker_router.leases == {}


def test_worker_lease_rebind_stops_before_launch(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    worker_router = StubWorkerRouter()
    calls: list[Any] = []

    def executor(request: Any) -> tuple[int, str, str, bool]:
        calls.append(request)
        return 0, "unexpected", "", False

    def checkpoint(request: Any) -> Mapping[str, Any]:
        worker_router.leases[request.task_id] = WorkerLease(
            "W-2",
            "coder",
            request.task_id,
            2.0,
            False,
        )
        return {"isolated": True, "checkpoint_id": request.task_id + ":cp"}

    orchestrator, _, worker_router, _, _ = make_orchestrator(
        root,
        worker_router=worker_router,
        executor=executor,
        checkpoint=checkpoint,
    )

    with pytest.raises(WorkerExecutionSafetyStop, match="identity"):
        orchestrator.run("TASK-REBIND")

    assert calls == []
    assert worker_router.released == ["TASK-REBIND:1"]


def test_validation_failure_stops_before_authorization(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    adapter = StubWorkerAdapter(validation={"passed": False, "reason": "criteria failed"})
    orchestrator, _, worker_router, _, authorization = make_orchestrator(
        root,
        worker_adapter=adapter,
    )

    with pytest.raises(IndependentValidationSafetyStop):
        orchestrator.run("TASK-VALIDATION")

    assert authorization.calls == 0
    assert worker_router.released == ["TASK-VALIDATION:1"]
    assert (root / "target.txt").read_text(encoding="utf-8") == 'VALUE = "before"'


def test_changed_target_mismatch_stops_before_execution(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    adapter = StubWorkerAdapter()

    def mismatched_prepare(
        task: Mapping[str, Any],
        assignment: Mapping[str, Any],
    ) -> WorkerExecutionSpec:
        del task, assignment
        return WorkerExecutionSpec(
            command=("pytest", "-q", "test_target.py"),
            targets=("test_target.py",),
            changed_targets=("other.txt",),
            changes=(
                FileChange("target.txt", 'VALUE = "before"', 'VALUE = "after"'),
            ),
        )

    adapter.prepare = mismatched_prepare  # type: ignore[method-assign]
    orchestrator, _, worker_router, _, _ = make_orchestrator(root, worker_adapter=adapter)

    with pytest.raises(OrchestrationSafetyStop, match="changed_targets"):
        orchestrator.run("TASK-TARGET")

    assert worker_router.released == ["TASK-TARGET:1"]


def test_validation_identity_mismatch_reaches_authorization_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = workspace(tmp_path)
    isolate_gate_files(monkeypatch, root)
    adapter = StubWorkerAdapter(
        validation={
            "passed": True,
            "task_id": "WRONG-TASK",
            "worker_id": "WRONG-WORKER",
        }
    )
    orchestrator, _, worker_router, _, _ = make_orchestrator(root, worker_adapter=adapter)
    orchestrator.authorization = ExecutionAuthorizationBoundary(root)

    with pytest.raises(ExecutionAuthorizationSafetyStop, match="task identity"):
        orchestrator.run("TASK-EVIDENCE")

    assert worker_router.released == ["TASK-EVIDENCE:1"]
    assert (root / "target.txt").read_text(encoding="utf-8") == 'VALUE = "before"'


def test_truncated_execution_cannot_reach_authorization(tmp_path: Path) -> None:
    root = workspace(tmp_path)

    def noisy_executor(request: Any) -> tuple[int, str, str, bool]:
        del request
        return 0, "x" * 2048, "", False

    orchestrator, _, worker_router, _, _ = make_orchestrator(
        root,
        executor=noisy_executor,
        max_output_chars=256,
    )

    with pytest.raises(IndependentValidationSafetyStop, match="Truncated"):
        orchestrator.run("TASK-TRUNCATED")

    assert worker_router.released == ["TASK-TRUNCATED:1"]


def test_missing_checkpoint_identity_stops_before_authorization(tmp_path: Path) -> None:
    root = workspace(tmp_path)

    def checkpoint(request: Any) -> Mapping[str, Any]:
        del request
        return {"isolated": True}

    orchestrator, _, worker_router, _, _ = make_orchestrator(
        root,
        checkpoint=checkpoint,
    )

    with pytest.raises(IndependentValidationSafetyStop, match="checkpoint_id"):
        orchestrator.run("TASK-CHECKPOINT")

    assert worker_router.released == ["TASK-CHECKPOINT:1"]
