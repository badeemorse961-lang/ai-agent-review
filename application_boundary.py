from __future__ import annotations

import shutil
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, Protocol

from central_leader import CentralLeader, LeaderResponse
from control_center_core_contract import connection_read_model, connection_runtime_status_by_id, sync_and_get_read_model
from orchestration import CanonicalOrchestrator
from plan_decomposer import PlanDecomposer
from process_sandbox import ProcessSandbox
from project_understanding_pipeline import ProjectUnderstandingPipeline
from provider_transport import OpenAICompatibleTransport
from secret_redaction import SecretRedactor
from sandbox_policy import WorkspaceResourcePolicy
from terminal_executor import TerminalExecutor
from worker_router import WorkerRouter
from leader_router import LeaderRouter

@dataclass(frozen=True)
class ApplicationIntent:
    kind: str
    payload: Mapping[str, Any]
    def validate(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("Application intent kind must be non-empty")
        if not isinstance(self.payload, Mapping):
            raise ValueError("Application intent payload must be an object")

@dataclass(frozen=True)
class ApplicationResult:
    status: str
    data: Mapping[str, Any]
    error: str | None = None

class GitInspectionAdapter(Protocol):
    def snapshot(self) -> Mapping[str, Any]: ...

class SafeGitInspectionAdapter:
    def __init__(self, workspace_root: Path) -> None:
        root = workspace_root.resolve()
        git = shutil.which("git")
        if not git:
            raise RuntimeError("git executable is not available")
        self.git_executable = str(Path(git).resolve())
        policy = WorkspaceResourcePolicy(root, allowed_tool_paths=[self.git_executable])
        self.executor = TerminalExecutor(ProcessSandbox(policy, timeout_seconds=30, max_output_chars=20_000))
    def snapshot(self) -> Mapping[str, Any]:
        commands = {"branch": (self.git_executable, "rev-parse", "--abbrev-ref", "HEAD"), "head": (self.git_executable, "rev-parse", "HEAD"), "status": (self.git_executable, "status", "--short")}
        result: dict[str, Any] = {}
        for name, command in commands.items():
            process = self.executor.run(command)
            if process.returncode != 0:
                return {"status": "UNKNOWN", "error": f"Git inspection failed for {name}"}
            result[name] = process.stdout.strip()
        result["clean"] = not bool(result.get("status"))
        result["authority"] = "inspection-only"
        return result

class ControlCenterService:
    def __init__(self, *, workspace_root: Path | None = None, leader_transport: Callable[[Any], Any] | None = None, leader_router: LeaderRouter | None = None, worker_router: WorkerRouter | None = None, orchestrator: CanonicalOrchestrator | None = None, git_inspector: GitInspectionAdapter | None = None, autowire_core: bool = True) -> None:
        self.workspace_root = workspace_root.resolve() if workspace_root else None
        self.leader_router = leader_router
        self.worker_router = worker_router
        self.leader_transport = leader_transport
        self.orchestrator = orchestrator
        self.git_inspector = git_inspector
        self.last_plan: Mapping[str, Any] | None = None
        self.last_run: Mapping[str, Any] | None = None
        self.events: list[dict[str, Any]] = []
        if autowire_core:
            self._autowire_core()
    def _autowire_core(self) -> None:
        if self.leader_router is None:
            try:
                self.leader_router = LeaderRouter()
            except Exception:
                self.leader_router = None
        if self.worker_router is None:
            try:
                self.worker_router = WorkerRouter()
            except Exception:
                self.worker_router = None
        if self.leader_transport is None:
            try:
                self.leader_transport = OpenAICompatibleTransport()
            except Exception:
                self.leader_transport = None
    def dispatch(self, intent: ApplicationIntent) -> ApplicationResult:
        intent.validate()
        handlers = {"select_project": self._select_project, "refresh_dashboard": self._dashboard, "send_leader_goal": self._send_leader_goal, "run_task": self._run_task, "refresh_connections": self._connections, "sync_external_secret_sources": self._sync_external_secret_sources, "git_snapshot": self._git_snapshot, "session_evidence": self._session_evidence}
        handler = handlers.get(intent.kind)
        if handler is None:
            return ApplicationResult("REJECTED", {}, f"Unknown application intent: {intent.kind}")
        try:
            result = handler(intent.payload)
        except Exception as exc:
            result = ApplicationResult("ERROR", {}, f"{type(exc).__name__}: {exc}")
        self._record_event(intent, result)
        return result
    def _select_project(self, payload: Mapping[str, Any]) -> ApplicationResult:
        raw = payload.get("workspace_root")
        if not isinstance(raw, str) or not raw.strip(): return ApplicationResult("REJECTED", {}, "workspace_root is required")
        root = Path(raw).expanduser().resolve()
        if not root.exists() or not root.is_dir(): return ApplicationResult("REJECTED", {}, "Selected workspace does not exist")
        self.workspace_root = root; self.git_inspector = SafeGitInspectionAdapter(root)
        return ApplicationResult("OK", {"workspace_root": str(root)})
    def _dashboard(self, payload: Mapping[str, Any]) -> ApplicationResult:
        del payload
        if self.workspace_root is None: return ApplicationResult("OK", {"project": None, "leader": {}, "workers": {}, "git": {}, "last_run": None})
        understanding = ProjectUnderstandingPipeline(self.workspace_root).analyze()
        return ApplicationResult("OK", {"project": dict(understanding.get("project", {})), "understanding": understanding, "leader": self._safe_router_snapshot(self.leader_router), "workers": self._safe_router_snapshot(self.worker_router), "git": self.git_inspector.snapshot() if self.git_inspector else {}, "last_plan": dict(self.last_plan) if isinstance(self.last_plan, Mapping) else None, "last_run": dict(self.last_run) if isinstance(self.last_run, Mapping) else None})
    def _send_leader_goal(self, payload: Mapping[str, Any]) -> ApplicationResult:
        goal = payload.get("goal"); task_id = payload.get("task_id")
        if not isinstance(goal, str) or not goal.strip() or not isinstance(task_id, str) or not task_id.strip(): return ApplicationResult("REJECTED", {}, "goal and task_id are required")
        if self.workspace_root is None: return ApplicationResult("REJECTED", {}, "No active project is selected")
        if self.leader_router is None or self.leader_transport is None: return ApplicationResult("BLOCKED", {}, "Leader transport/router is not configured")
        context = dict(ProjectUnderstandingPipeline(self.workspace_root).analyze().get("context", {})); context["operator_request"] = {"goal": goal.strip(), "task_id": task_id.strip()}
        leader = CentralLeader(router=self.leader_router, transport=self.leader_transport)
        try: response: LeaderResponse = leader.plan(task_id.strip(), context)
        finally:
            try: leader.release(task_id.strip())
            except Exception: pass
        plan = PlanDecomposer().decompose(response.payload, context=context); self.last_plan = dict(plan)
        return ApplicationResult("OK", {"task_id": task_id.strip(), "goal": goal.strip(), "leader_response": {"payload": SecretRedactor().redact_value(response.payload), "account_id": response.account_id, "model": response.model, "tier": response.tier}, "plan": dict(plan)})
    def _run_task(self, payload: Mapping[str, Any]) -> ApplicationResult:
        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip(): return ApplicationResult("REJECTED", {}, "task_id is required")
        if self.orchestrator is None: return ApplicationResult("BLOCKED", {}, "Canonical production orchestrator is not configured; no task was executed")
        result = self.orchestrator.run(task_id.strip()); self.last_run = result.to_dict(); self.last_plan = dict(result.plan)
        return ApplicationResult("OK", self.last_run)
    def _connections(self, payload: Mapping[str, Any]) -> ApplicationResult:
        del payload
        return ApplicationResult("OK", connection_read_model(connection_runtime_status_by_id((self.leader_router, self.worker_router))))
    def _sync_external_secret_sources(self, payload: Mapping[str, Any]) -> ApplicationResult:
        del payload
        runtime = connection_runtime_status_by_id((self.leader_router, self.worker_router))
        return ApplicationResult("OK", sync_and_get_read_model(runtime))
    def _git_snapshot(self, payload: Mapping[str, Any]) -> ApplicationResult:
        del payload
        if self.workspace_root and self.git_inspector is None:
            try: self.git_inspector = SafeGitInspectionAdapter(self.workspace_root)
            except Exception as exc: return ApplicationResult("NOT_CONFIGURED", {}, str(exc))
        if self.git_inspector is None: return ApplicationResult("NOT_CONFIGURED", {}, "No active project is selected")
        snapshot = self.git_inspector.snapshot(); return ApplicationResult("OK", dict(snapshot) if isinstance(snapshot, Mapping) else {})
    def _session_evidence(self, payload: Mapping[str, Any]) -> ApplicationResult:
        del payload
        return ApplicationResult("OK", {"events": list(self.events), "last_plan": self.last_plan, "last_run": self.last_run})
    def _record_event(self, intent: ApplicationIntent, result: ApplicationResult) -> None:
        redactor = SecretRedactor(); self.events.append({"intent": intent.kind, "status": result.status, "data": redactor.redact_value(result.data), "error": redactor.redact_text(result.error) if result.error else None})
        if len(self.events) > 100: del self.events[:-100]
    @staticmethod
    def _safe_router_snapshot(router: Any) -> dict[str, Any]:
        if router is None: return {}
        value = router.snapshot(); return dict(value) if isinstance(value, Mapping) else {}
