from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from central_leader import CentralLeader, LeaderResponse
from connection_manager import (
    PROVIDER_FILES,
    PROVIDER_PREFIXES,
    import_provider,
    load_registry,
    read_secret_source,
    resolve_secret_file,
    save_registry,
)
from process_sandbox import ProcessSandbox
from project_understanding_pipeline import ProjectUnderstandingPipeline
from secret_redaction import SecretRedactor
from sandbox_policy import WorkspaceResourcePolicy
from terminal_executor import TerminalExecutor
from worker_router import WorkerRouter
from leader_router import LeaderRouter


@dataclass(frozen=True)
class ApplicationIntent:
    """Typed, structured user intent crossing the desktop application boundary."""

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


@dataclass(frozen=True)
class ConnectionView:
    connection_id: str
    provider: str
    model: str | None
    assignments: tuple[str, ...]
    configured: bool
    metadata_status: str
    runtime_status: str
    fingerprint_present: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "provider": self.provider,
            "model": self.model,
            "assignments": list(self.assignments),
            "configured": self.configured,
            "metadata_status": self.metadata_status,
            "runtime_status": self.runtime_status,
            "fingerprint_present": self.fingerprint_present,
        }


class GitInspectionAdapter(Protocol):
    def snapshot(self) -> Mapping[str, Any]: ...


class SafeGitInspectionAdapter:
    """Uses the existing inspection-only TerminalExecutor/GitSafetyPolicy path."""

    def __init__(self, workspace_root: Path) -> None:
        root = workspace_root.resolve()
        git = shutil.which("git")
        if not git:
            raise RuntimeError("git executable is not available")
        policy = WorkspaceResourcePolicy(root, allowed_tool_paths=[git])
        sandbox = ProcessSandbox(policy, timeout_seconds=30, max_output_chars=20_000)
        self.executor = TerminalExecutor(sandbox)

    def snapshot(self) -> Mapping[str, Any]:
        commands = {
            "branch": ("git", "rev-parse", "--abbrev-ref", "HEAD"),
            "head": ("git", "rev-parse", "HEAD"),
            "status": ("git", "status", "--short"),
        }
        result: dict[str, Any] = {}
        for name, command in commands.items():
            process = self.executor.run(command)
            if process.returncode != 0:
                return {
                    "status": "UNKNOWN",
                    "error": f"Git inspection failed for {name}",
                }
            result[name] = process.stdout.strip()
        result["clean"] = not bool(result.get("status"))
        result["authority"] = "inspection-only"
        return result


class ControlCenterService:
    """Application layer over authoritative Core services and read models."""

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        leader_transport: Callable[[Any], Any] | None = None,
        leader_router: LeaderRouter | None = None,
        worker_router: WorkerRouter | None = None,
        git_inspector: GitInspectionAdapter | None = None,
    ) -> None:
        self.workspace_root = workspace_root.resolve() if workspace_root else None
        self.leader_router = leader_router
        self.worker_router = worker_router
        self.leader_transport = leader_transport
        self.git_inspector = git_inspector
        self.last_plan: Mapping[str, Any] | None = None
        self.events: list[dict[str, Any]] = []

    def dispatch(self, intent: ApplicationIntent) -> ApplicationResult:
        intent.validate()
        handlers = {
            "select_project": self._select_project,
            "refresh_dashboard": self._dashboard,
            "send_leader_goal": self._send_leader_goal,
            "refresh_connections": self._connections,
            "import_provider_connections": self._import_provider_connections,
            "git_snapshot": self._git_snapshot,
            "session_evidence": self._session_evidence,
        }
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
        if not isinstance(raw, str) or not raw.strip():
            return ApplicationResult("REJECTED", {}, "workspace_root is required")
        root = Path(raw).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return ApplicationResult("REJECTED", {}, "Selected workspace does not exist")
        self.workspace_root = root
        self.git_inspector = SafeGitInspectionAdapter(root)
        return ApplicationResult("OK", {"workspace_root": str(root)})

    def _dashboard(self, payload: Mapping[str, Any]) -> ApplicationResult:
        del payload
        if self.workspace_root is None:
            return ApplicationResult("OK", {"project": None, "leader": {}, "workers": {}})
        understanding = ProjectUnderstandingPipeline(self.workspace_root).analyze()
        return ApplicationResult(
            "OK",
            {
                "project": dict(understanding.get("project", {})),
                "understanding": understanding,
                "leader": self._safe_router_snapshot(self.leader_router),
                "workers": self._safe_router_snapshot(self.worker_router),
                "git": self.git_inspector.snapshot() if self.git_inspector else {},
                "last_plan": dict(self.last_plan) if isinstance(self.last_plan, Mapping) else None,
            },
        )

    def _send_leader_goal(self, payload: Mapping[str, Any]) -> ApplicationResult:
        goal = payload.get("goal")
        task_id = payload.get("task_id")
        if not isinstance(goal, str) or not goal.strip():
            return ApplicationResult("REJECTED", {}, "goal is required")
        if not isinstance(task_id, str) or not task_id.strip():
            return ApplicationResult("REJECTED", {}, "task_id is required")
        if self.workspace_root is None:
            return ApplicationResult("REJECTED", {}, "No active project is selected")
        if self.leader_router is None or self.leader_transport is None:
            return ApplicationResult("BLOCKED", {}, "Leader transport/router is not configured")

        understanding = ProjectUnderstandingPipeline(self.workspace_root).analyze()
        context = dict(understanding.get("context", {}))
        context["operator_request"] = {"goal": goal.strip(), "task_id": task_id.strip()}
        leader = CentralLeader(router=self.leader_router, transport=self.leader_transport)
        try:
            response: LeaderResponse = leader.plan(task_id.strip(), context)
        finally:
            try:
                leader.release(task_id.strip())
            except Exception:
                pass
        redactor = SecretRedactor()
        payload_value = redactor.redact_value(response.payload)
        data = {
            "task_id": task_id.strip(),
            "goal": goal.strip(),
            "leader_response": {
                "payload": payload_value,
                "account_id": response.account_id,
                "model": response.model,
                "tier": response.tier,
            },
        }
        if isinstance(payload_value, Mapping) and isinstance(payload_value.get("plan"), Mapping):
            self.last_plan = dict(payload_value["plan"])
        return ApplicationResult("OK", data)

    def _connections(self, payload: Mapping[str, Any]) -> ApplicationResult:
        del payload
        registry = load_registry()
        connections_meta = registry.get("connections", {})
        authoritative = self._registry_assignments(registry)
        views: list[ConnectionView] = []
        for connection_id in sorted(authoritative | set(connections_meta)):
            item = connections_meta.get(connection_id, {})
            provider = str(item.get("provider", "unknown")) if isinstance(item, Mapping) else "unknown"
            views.append(
                ConnectionView(
                    connection_id=connection_id,
                    provider=provider,
                    model=self._model_for_connection(registry, connection_id),
                    assignments=tuple(sorted(authoritative.get(connection_id, set()))),
                    configured=connection_id in authoritative,
                    metadata_status=str(item.get("status", "UNKNOWN")) if isinstance(item, Mapping) else "UNKNOWN",
                    runtime_status="UNOBSERVED",
                    fingerprint_present=isinstance(item, Mapping) and isinstance(item.get("key_fingerprint"), str),
                )
            )
        return ApplicationResult("OK", {"connections": [item.to_dict() for item in views]})

    def _import_provider_connections(self, payload: Mapping[str, Any]) -> ApplicationResult:
        provider = payload.get("provider")
        if provider not in PROVIDER_FILES:
            return ApplicationResult("REJECTED", {}, "provider must be groq or openrouter")
        source = resolve_secret_file(provider)
        registry = load_registry()
        import_provider(provider, source, registry, PROVIDER_PREFIXES[provider])
        save_registry(registry)
        labeled, unlabeled = read_secret_source(source, PROVIDER_PREFIXES[provider])
        return ApplicationResult(
            "OK",
            {
                "provider": provider,
                "imported_labeled": sorted(labeled),
                "imported_unlabeled_count": len(unlabeled),
                "raw_secrets_returned": False,
            },
        )

    def _git_snapshot(self, payload: Mapping[str, Any]) -> ApplicationResult:
        del payload
        if self.workspace_root and self.git_inspector is None:
            try:
                self.git_inspector = SafeGitInspectionAdapter(self.workspace_root)
            except Exception as exc:
                return ApplicationResult("NOT_CONFIGURED", {}, str(exc))
        if self.git_inspector is None:
            return ApplicationResult("NOT_CONFIGURED", {}, "No active project is selected")
        snapshot = self.git_inspector.snapshot()
        if not isinstance(snapshot, Mapping):
            return ApplicationResult("ERROR", {}, "Git inspection adapter returned invalid data")
        return ApplicationResult("OK", dict(snapshot))

    def _session_evidence(self, payload: Mapping[str, Any]) -> ApplicationResult:
        del payload
        return ApplicationResult("OK", {"events": list(self.events), "last_plan": self.last_plan})

    def _record_event(self, intent: ApplicationIntent, result: ApplicationResult) -> None:
        redactor = SecretRedactor()
        self.events.append(
            {
                "intent": intent.kind,
                "status": result.status,
                "data": redactor.redact_value(result.data),
                "error": redactor.redact_text(result.error) if result.error else None,
            }
        )
        if len(self.events) > 100:
            del self.events[:-100]

    @staticmethod
    def _safe_router_snapshot(router: Any) -> dict[str, Any]:
        if router is None:
            return {}
        snapshot = router.snapshot()
        return dict(snapshot) if isinstance(snapshot, Mapping) else {}

    @staticmethod
    def _registry_assignments(registry: Mapping[str, Any]) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        architecture = registry.get("architecture", {})
        if isinstance(architecture, Mapping):
            leader = architecture.get("leader", {})
            if isinstance(leader, Mapping):
                for connection_id in list(leader.get("primary_pool", [])) + list(leader.get("failover_pool", [])):
                    if isinstance(connection_id, str):
                        result.setdefault(connection_id, set()).add("leader")
            workers = architecture.get("workers", {})
            if isinstance(workers, Mapping):
                roles = workers.get("roles", {})
                if isinstance(roles, Mapping):
                    for role, ids in roles.items():
                        if isinstance(role, str) and isinstance(ids, list):
                            for connection_id in ids:
                                if isinstance(connection_id, str):
                                    result.setdefault(connection_id, set()).add(role)
        return result

    @staticmethod
    def _model_for_connection(registry: Mapping[str, Any], connection_id: str) -> str | None:
        architecture = registry.get("architecture", {})
        if not isinstance(architecture, Mapping):
            return None
        leader = architecture.get("leader", {})
        if isinstance(leader, Mapping):
            primary = leader.get("primary_pool", [])
            failover = leader.get("failover_pool", [])
            if connection_id in list(primary) + list(failover):
                models = [leader.get("primary_model"), leader.get("failover_model")]
                return " / ".join(str(model) for model in models if model) or None
        workers = architecture.get("workers", {})
        if isinstance(workers, Mapping):
            roles = workers.get("roles", {})
            if isinstance(roles, Mapping) and any(isinstance(ids, list) and connection_id in ids for ids in roles.values()):
                model = workers.get("model")
                return str(model) if model else None
        return None
