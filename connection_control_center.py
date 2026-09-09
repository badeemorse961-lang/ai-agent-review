from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from application_boundary import ApplicationIntent, ApplicationResult, ControlCenterService
from connection_manager import PENDING_ASSIGNMENT, disable_connection, enable_connection, get_connection_status, load_registry as load_connection_metadata, mark_connection_failed, remove_connection, validate_connection
from control_center_core_contract import replace_connection_credential_from_ui
from desktop_control_center import ControlCenterApp
from leader_router import LeaderRouter
from provider_transport import OpenAICompatibleTransport
from worker_router import WorkerRouter


class ConnectionControlCenterService(ControlCenterService):
    """Application intent adapter; connection policy and credentials stay in Core."""

    def __init__(self, **kwargs: Any) -> None:
        self.last_connection_operation: Mapping[str, Any] | None = None
        secret_store = kwargs.pop("secret_store", None)
        if secret_store is not None:
            kwargs.setdefault("leader_transport", OpenAICompatibleTransport(secret_store=secret_store))
        elif kwargs.get("autowire_core", True) and "leader_transport" not in kwargs:
            kwargs["leader_transport"] = OpenAICompatibleTransport()
        super().__init__(**kwargs)

    def dispatch(self, intent: ApplicationIntent) -> ApplicationResult:
        intent.validate()
        handler = {"replace_connection_credential": self._replace_connection_credential, "validate_connection": self._validate_connection, "disable_connection": self._disable_connection, "enable_connection": self._enable_connection, "remove_connection": self._remove_connection, "mark_connection_failed": self._mark_connection_failed}.get(intent.kind)
        if handler is None:
            return super().dispatch(intent)
        try:
            result = handler(intent.payload)
        except Exception as exc:
            result = ApplicationResult("ERROR", {}, f"{type(exc).__name__}: {exc}")
        self._record_event(intent, result)
        self.last_connection_operation = dict(result.data)
        return result

    def _reload_router_state(self) -> None:
        if self.leader_router is not None:
            try: self.leader_router = LeaderRouter()
            except Exception: self.leader_router = None
        if self.worker_router is not None:
            try: self.worker_router = WorkerRouter()
            except Exception: self.worker_router = None

    @staticmethod
    def _registry_item(connection_id: Any) -> tuple[str, dict[str, Any], dict[str, Any]]:
        if not isinstance(connection_id, str) or not connection_id.strip(): raise ValueError("connection_id is required")
        registry = load_connection_metadata(); connections = registry.get("connections", {})
        item = connections.get(connection_id) if isinstance(connections, Mapping) else None
        if not isinstance(item, dict): raise KeyError(f"Connection not found: {connection_id}")
        return connection_id, item, registry

    def _replace_connection_credential(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id = payload.get("connection_id"); source_path = payload.get("source_path")
        if not isinstance(connection_id, str) or not connection_id.strip() or not isinstance(source_path, str) or not source_path.strip(): return ApplicationResult("REJECTED", {}, "connection_id and source_path are required")
        data = replace_connection_credential_from_ui(connection_id, source_path); self._reload_router_state(); return ApplicationResult("OK", data)

    def _validate_connection(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, _, registry = self._registry_item(payload.get("connection_id"))
        try: item = validate_connection(connection_id, registry=registry)
        except Exception as exc:
            self._reload_router_state(); return ApplicationResult("FAILED", {"connection_id": connection_id, "status": get_connection_status(connection_id, registry)}, f"{type(exc).__name__}: {exc}"[:240])
        self._reload_router_state(); return ApplicationResult("OK", {"connection_id": connection_id, "status": item.get("status"), "credential_validated": True})

    def _disable_connection(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, _, registry = self._registry_item(payload.get("connection_id")); item = disable_connection(connection_id, registry); self._reload_router_state(); return ApplicationResult("OK", {"connection_id": connection_id, "status": item["status"]})

    def _enable_connection(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, item, registry = self._registry_item(payload.get("connection_id"))
        if item.get("status") == PENDING_ASSIGNMENT: return ApplicationResult("BLOCKED", {"connection_id": connection_id, "status": PENDING_ASSIGNMENT, "active": False, "routable": False}, "PENDING_ASSIGNMENT requires explicit Core assignment and admission")
        try: result = enable_connection(connection_id, registry)
        except ValueError as exc: return ApplicationResult("BLOCKED", {"connection_id": connection_id, "status": get_connection_status(connection_id, registry)}, str(exc))
        self._reload_router_state(); return ApplicationResult("OK", {"connection_id": connection_id, "status": result["status"]})

    def _remove_connection(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, _, registry = self._registry_item(payload.get("connection_id"))
        if payload.get("confirmed") is not True: return ApplicationResult("REJECTED", {"connection_id": connection_id}, "Explicit confirmation is required")
        try: remove_connection(connection_id, registry=registry)
        except ValueError as exc: return ApplicationResult("BLOCKED", {"connection_id": connection_id, "status": get_connection_status(connection_id, registry)}, str(exc))
        self._reload_router_state(); return ApplicationResult("OK", {"connection_id": connection_id, "status": "REMOVED"})

    def _mark_connection_failed(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, _, registry = self._registry_item(payload.get("connection_id")); reason = payload.get("reason")
        item = mark_connection_failed(connection_id, invalid=bool(payload.get("invalid")), reason=reason if isinstance(reason, str) else None, registry=registry); self._reload_router_state(); return ApplicationResult("OK", {"connection_id": connection_id, "status": item["status"], "reason": item.get("failure_reason", "")})


class ConnectionControlCenterApp(ControlCenterApp):
    """Historical desktop surface backed by the current Core connection contract."""

    def __init__(self) -> None:
        super().__init__(service=ConnectionControlCenterService()); self.connection_tree: Any | None = None

    def _connections(self) -> None:
        self._header("Connections & Pools", "Core-backed connection metadata, assignments, readiness, runtime health and external source evidence.", action=self._sync_external_sources, action_text="Refresh External Sources")
        result = self.service.dispatch(ApplicationIntent("refresh_connections", {})); self.body.rowconfigure(0, weight=1)
        tree = self.ttk.Treeview(self.body, columns=("id", "provider", "model", "assignment", "status", "active", "routable", "ready", "health", "fingerprint", "credential", "reason"), show="headings", selectmode="browse")
        labels = {"id":"Connection ID","provider":"Provider","model":"Model","assignment":"Assignment","status":"Status","active":"Active","routable":"Routable","ready":"Readiness","health":"Health","fingerprint":"Fingerprint","credential":"Credential","reason":"Reason"}; widths = {"id":105,"provider":90,"model":210,"assignment":145,"status":125,"active":70,"routable":78,"ready":125,"health":105,"fingerprint":125,"credential":90,"reason":300}
        for column in tree["columns"]: tree.heading(column, text=labels[column]); tree.column(column, width=widths[column], minwidth=70, anchor="w")
        palette = self.palette[self.dark]
        for state, color in (("READY", palette["good"]),("STORED", palette["muted"]),("PENDING_ASSIGNMENT", palette["warn"]),("SETUP", palette["warn"]),("FAILED", palette["bad"]),("REMOVED", palette["muted"])): tree.tag_configure(state, foreground=color)
        connections = result.data.get("connections", []) if isinstance(result.data, Mapping) else []
        for raw in connections:
            item = self._mapping(raw); readiness = str(item.get("ready_state", "SETUP")); assignment = ", ".join(item.get("assignments", [])) if isinstance(item.get("assignments"), list) and item.get("assignments") else "unassigned"
            tree.insert("", "end", values=(item.get("connection_id", ""), item.get("provider", ""), item.get("model") or "—", assignment, item.get("metadata_status", "UNKNOWN"), "yes" if item.get("active") else "no", "yes" if item.get("routable") else "no", readiness, item.get("runtime_status", "UNOBSERVED"), item.get("fingerprint_display", "absent"), "present" if item.get("credential_present") else "absent", item.get("ready_reason", "")), tags=(readiness,))
        tree.grid(row=0, column=0, sticky="nsew"); self.connection_tree = tree

        sources = result.data.get("external_secret_sources", {}) if isinstance(result.data, Mapping) else {}; providers = sources.get("providers", {}) if isinstance(sources, Mapping) else {}
        source_frame = self.ttk.LabelFrame(self.body, text="External Secret Sources", padding=8); source_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        last_sync = sources.get("last_sync_at", "NOT AVAILABLE") if isinstance(sources, Mapping) else "NOT AVAILABLE"; rows = [("Last sync", last_sync)]
        for provider in ("groq", "openrouter"):
            info = providers.get(provider, {}) if isinstance(providers, Mapping) else {}; pending = sum(1 for raw in connections if isinstance(raw, Mapping) and raw.get("provider") == provider and raw.get("metadata_status") == PENDING_ASSIGNMENT)
            rows.append((provider.upper(), f"exists={info.get('source_exists', False)} | path={info.get('source_path', '—')} | imported={info.get('newly_imported', 0)} | already={info.get('already_known', 0)} | rejected={info.get('rejected', info.get('invalid', 0))} | failed={info.get('failed', 0)} | pending={pending}"))
        for index, (title, value) in enumerate(rows):
            self.ttk.Label(source_frame, text=title, style="CardTitle.TLabel").grid(row=index, column=0, sticky="w", padx=(0, 12), pady=2); self.ttk.Label(source_frame, text=str(value), style="Subtitle.TLabel", wraplength=1050, justify="left").grid(row=index, column=1, sticky="w", pady=2)

        toolbar = self.ttk.Frame(self.body); toolbar.grid(row=2, column=0, sticky="ew", pady=(8, 0)); actions = (("Refresh External Sources", self._sync_external_sources),("Replace / Rotate", lambda: self._connection_action("replace_connection_credential")),("Validate", lambda: self._connection_action("validate_connection")),("Disable", lambda: self._connection_action("disable_connection")),("Enable", lambda: self._connection_action("enable_connection")),("Remove", lambda: self._connection_action("remove_connection")))
        for text, command in actions: self.ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=(0, 5))
        self._set_status(result, "Connection state refreshed from Core")

    def _sync_external_sources(self) -> None:
        result = self.service.dispatch(ApplicationIntent("sync_external_secret_sources", {})); self.show("Connections & Pools"); self._set_status(result, "External secret sources synchronized")

    def _selected_connection_id(self) -> str | None:
        if self.connection_tree is None: return None
        selection = self.connection_tree.selection()
        if not selection: return None
        values = self.connection_tree.item(selection[0], "values"); return str(values[0]) if values else None

    def _connection_action(self, action: str) -> None:
        from tkinter import filedialog, messagebox
        connection_id = self._selected_connection_id()
        if not connection_id: self._set_status(ApplicationResult("REJECTED", {}, "Select a connection first")); return
        payload: dict[str, Any] = {"connection_id": connection_id}
        if action == "replace_connection_credential":
            path = filedialog.askopenfilename(title=f"Replace credential for {connection_id}", filetypes=[("Text files", "*.txt")])
            if not path: return
            payload["source_path"] = str(Path(path).resolve())
        elif action == "remove_connection":
            if not messagebox.askyesno("Remove connection", f"Remove {connection_id}?"): return
            payload["confirmed"] = True
        result = self.service.dispatch(ApplicationIntent(action, payload)); self.show("Connections & Pools"); self._set_status(result)


def main() -> int:
    ConnectionControlCenterApp().run(); return 0
