from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from application_boundary import ApplicationIntent, ApplicationResult, ControlCenterService
from connection_manager import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_DISABLED,
    disable_connection,
    enable_connection,
    get_connection_status,
    import_provider,
    load_registry,
    mark_connection_failed,
    remove_connection,
)
from desktop_control_center import ControlCenterApp
from leader_router import LeaderRouter
from protected_secret_store import SecretStore, WindowsProtectedSecretStore
from worker_router import WorkerRouter


class ConnectionControlCenterService(ControlCenterService):
    """Adds explicit protected connection lifecycle intents over the existing Core routers."""

    def __init__(self, *, secret_store: SecretStore | None = None, **kwargs: Any) -> None:
        self.secret_store = secret_store or WindowsProtectedSecretStore()
        self.last_connection_operation: Mapping[str, Any] | None = None
        super().__init__(**kwargs)

    def dispatch(self, intent: ApplicationIntent) -> ApplicationResult:
        intent.validate()
        if intent.kind == "refresh_connections":
            result = super().dispatch(intent)
            data = dict(result.data)
            items = data.get("connections", [])
            if isinstance(items, list):
                changed = False
                for item in items:
                    if not isinstance(item, Mapping):
                        continue
                    if item.get("runtime_status") != "FAILED":
                        continue
                    connection_id = item.get("connection_id")
                    current_status = str(item.get("metadata_status", ""))
                    if not isinstance(connection_id, str) or current_status in {"DISABLED", "FAILED", "INVALID"}:
                        continue
                    try:
                        registry = load_registry()
                        mark_connection_failed(
                            connection_id,
                            reason="runtime health validation reported the connection as unavailable",
                            registry=registry,
                        )
                        changed = True
                    except Exception:
                        pass
                if changed:
                    refreshed = super().dispatch(intent)
                    data = dict(refreshed.data)
                    return ApplicationResult(refreshed.status, data, refreshed.error)
            return result

        handler = {
            "import_provider_connections": self._import_provider_connections,
            "disable_connection": self._disable_connection,
            "enable_connection": self._enable_connection,
            "remove_connection": self._remove_connection,
            "mark_connection_failed": self._mark_connection_failed,
        }.get(intent.kind)
        if handler is None:
            return super().dispatch(intent)
        try:
            result = handler(intent.payload)
        except Exception as exc:
            result = ApplicationResult("ERROR", {}, f"{type(exc).__name__}: {exc}")
        self._record_event(intent, result)
        data = dict(result.data)
        data["result_status"] = result.status
        self.last_connection_operation = data
        return ApplicationResult(result.status, data, result.error)

    def _reload_router_state(self) -> None:
        if self.leader_router is not None:
            try:
                self.leader_router = LeaderRouter()
            except Exception:
                self.leader_router = None
        if self.worker_router is not None:
            try:
                self.worker_router = WorkerRouter()
            except Exception:
                self.worker_router = None

    def _import_provider_connections(self, payload: Mapping[str, Any]) -> ApplicationResult:
        provider = payload.get("provider")
        source_path = payload.get("source_path")
        if provider not in {"groq", "openrouter"}:
            return ApplicationResult("REJECTED", {}, "provider must be groq or openrouter")
        if not isinstance(source_path, str) or not source_path.strip():
            return ApplicationResult("REJECTED", {}, "TXT import source is required")
        path = Path(source_path).expanduser().resolve()
        if path.suffix.lower() != ".txt" or not path.is_file():
            return ApplicationResult("REJECTED", {}, "Selected import source must be an existing .txt file")
        registry = load_registry()
        summary = import_provider(
            provider,
            path,
            registry,
            "GROQ" if provider == "groq" else "OR",
            secret_store=self.secret_store,
        )
        return ApplicationResult(
            "NO_CHANGES" if summary.imported_count == 0 and summary.rejected_count == 0 else "OK",
            summary.to_dict(),
        )

    def _connection_from_payload(self, payload: Mapping[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
        connection_id = payload.get("connection_id")
        if not isinstance(connection_id, str) or not connection_id.strip():
            raise ValueError("connection_id is required")
        registry = load_registry()
        item = registry.get("connections", {}).get(connection_id)
        if not isinstance(item, dict):
            raise KeyError(f"Connection not found: {connection_id}")
        return connection_id, item, registry

    def _disable_connection(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, _, registry = self._connection_from_payload(payload)
        disable_connection(connection_id, registry)
        self._reload_router_state()
        return ApplicationResult("OK", {"connection_id": connection_id, "status": LIFECYCLE_DISABLED})

    def _enable_connection(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, _, registry = self._connection_from_payload(payload)
        if not self.secret_store.has(connection_id):
            return ApplicationResult(
                "BLOCKED",
                {"connection_id": connection_id, "status": get_connection_status(connection_id, registry)},
                "Protected credential is unavailable",
            )
        try:
            result = enable_connection(connection_id, registry)
        except ValueError as exc:
            return ApplicationResult(
                "BLOCKED",
                {
                    "connection_id": connection_id,
                    "status": get_connection_status(connection_id, registry),
                    "setup_required": "REGISTRY_ASSIGNMENT",
                },
                str(exc),
            )
        self._reload_router_state()
        return ApplicationResult("OK", {"connection_id": connection_id, "status": result["status"]})

    def _remove_connection(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, _, registry = self._connection_from_payload(payload)
        if payload.get("confirmed") is not True:
            return ApplicationResult("REJECTED", {"connection_id": connection_id}, "Explicit confirmation is required")
        remove_connection(connection_id, registry=registry, secret_store=self.secret_store)
        self._reload_router_state()
        return ApplicationResult("OK", {"connection_id": connection_id, "status": "REMOVED"})

    def _mark_connection_failed(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, _, registry = self._connection_from_payload(payload)
        invalid = bool(payload.get("invalid"))
        reason = payload.get("reason")
        safe_reason = reason[:240] if isinstance(reason, str) else None
        result = mark_connection_failed(connection_id, invalid=invalid, reason=safe_reason, registry=registry)
        self._reload_router_state()
        return ApplicationResult("OK", {"connection_id": connection_id, "status": result["status"], "reason": result.get("failure_reason", "")})


class ConnectionControlCenterApp(ControlCenterApp):
    """Same Control Center shell with the protected connection lifecycle surface."""

    def __init__(self) -> None:
        super().__init__(service=ConnectionControlCenterService())
        self.connection_tree: Any | None = None

    def _connections(self) -> None:
        self._header(
            "Connections & Pools",
            "✓ READY = securely stored + assigned + active. Stored-only connections are not routed; assignment remains config/registry.json.",
            action=lambda: self.show("Connections & Pools"),
            action_text="Refresh",
        )
        result = self.service.dispatch(ApplicationIntent("refresh_connections", {}))
        self.body.rowconfigure(0, weight=1)
        tree = self.ttk.Treeview(
            self.body,
            columns=("id", "provider", "model", "assignment", "status", "ready", "runtime", "fingerprint"),
            show="headings",
            selectmode="browse",
        )
        labels = {
            "id": "Connection ID",
            "provider": "Provider",
            "model": "Model",
            "assignment": "Assignment",
            "status": "Status",
            "ready": "Automatic Use",
            "runtime": "Runtime / Health",
            "fingerprint": "Fingerprint",
        }
        widths = {
            "id": 120,
            "provider": 100,
            "model": 240,
            "assignment": 160,
            "status": 105,
            "ready": 125,
            "runtime": 125,
            "fingerprint": 100,
        }
        for column in tree["columns"]:
            tree.heading(column, text=labels[column])
            tree.column(column, width=widths[column], anchor="w")
        connections = result.data.get("connections", []) if isinstance(result.data, Mapping) else []
        palette = self.palette[self.dark]
        tree.tag_configure("READY", foreground=palette["good"])
        tree.tag_configure("STORED", foreground=palette["muted"])
        tree.tag_configure("SETUP", foreground=palette["warn"])
        tree.tag_configure("FAILED", foreground=palette["bad"])
        tree.tag_configure("REMOVED", foreground=palette["muted"])
        for item in connections:
            item = self._mapping(item)
            readiness, _reason = self._connection_readiness(item)
            ready_label = {
                "READY": "✓ READY",
                "STORED": "● STORED",
                "SETUP": "⚠ SETUP",
                "FAILED": "✕ FAILED",
                "REMOVED": "— REMOVED",
            }.get(readiness, "? UNKNOWN")
            raw_status = str(item.get("metadata_status", "UNKNOWN"))
            display_status = "ACTIVE" if raw_status == "VALIDATED" else raw_status
            assignment = ", ".join(item.get("assignments", [])) if isinstance(item.get("assignments"), list) else "unassigned"
            values = (
                item.get("connection_id", ""),
                item.get("provider", ""),
                item.get("model", ""),
                assignment,
                display_status,
                ready_label,
                item.get("runtime_status", "UNOBSERVED"),
                "present" if item.get("fingerprint_present") else "absent",
            )
            tree.insert("", "end", values=values, tags=(readiness,))
        tree.grid(row=0, column=0, sticky="nsew")
        self.connection_tree = tree

        toolbar = self.ttk.Frame(self.body)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for provider, label in (("openrouter", "Import OpenRouter TXT"), ("groq", "Import Groq TXT")):
            self.ttk.Button(toolbar, text=label, command=lambda p=provider: self._import(p)).pack(side="left", padx=(0, 8))
        for action, label in (("disable_connection", "Disable"), ("enable_connection", "Enable"), ("remove_connection", "Remove")):
            self.ttk.Button(toolbar, text=label, command=lambda a=action: self._connection_action(a)).pack(side="left", padx=(0, 8))

        operation = getattr(self.service, "last_connection_operation", None)
        if isinstance(operation, Mapping):
            self._show_connection_operation(toolbar, operation)
        else:
            self._set_status(result, "Connection registry refreshed")

    def _connection_readiness(self, item: Mapping[str, Any]) -> tuple[str, str]:
        """Derive a truthful UI-only readiness marker from Core state and protected-store presence."""
        status = str(item.get("metadata_status", "UNKNOWN")).upper()
        runtime = str(item.get("runtime_status", "UNOBSERVED")).upper()
        connection_id = item.get("connection_id")
        assigned = isinstance(item.get("assignments"), list) and bool(item.get("assignments"))
        credential_present = False
        if isinstance(connection_id, str):
            try:
                credential_present = self.service.secret_store.has(connection_id)
            except Exception:
                return "SETUP", "Protected store unavailable"

        if status == "REMOVED":
            return "REMOVED", "Removed"
        if status in {"FAILED", "INVALID"} or runtime == "FAILED":
            return "FAILED", "Not ready"
        if not credential_present:
            return "SETUP", "Credential not stored"
        if not assigned:
            return "STORED", "Stored · awaiting registry assignment"
        if status == "DISABLED":
            return "STORED", "Stored · manually disabled"
        if status in {"ACTIVE", "VALIDATED"} and runtime != "FAILED":
            return "READY", "Ready · automatic use"
        return "SETUP", "Needs validation"

    def _selected_connection_id(self) -> str | None:
        if self.connection_tree is None:
            return None
        selection = self.connection_tree.selection()
        if not selection:
            return None
        values = self.connection_tree.item(selection[0], "values")
        return str(values[0]) if values else None

    def _import(self, provider: str) -> None:
        from tkinter import filedialog
        path = filedialog.askopenfilename(title=f"Import {provider} TXT source", filetypes=[("Text files", "*.txt")])
        if not path:
            return
        result = self.service.dispatch(ApplicationIntent("import_provider_connections", {"provider": provider, "source_path": path}))
        self.show("Connections & Pools")
        self._set_status(result)

    def _connection_action(self, action: str) -> None:
        from tkinter import messagebox
        connection_id = self._selected_connection_id()
        if not connection_id:
            self._set_status(ApplicationResult("REJECTED", {}, "Select a connection first"))
            return
        payload: dict[str, Any] = {"connection_id": connection_id}
        if action == "remove_connection":
            confirmed = messagebox.askyesno("Remove connection", f"Remove {connection_id}? The protected credential will be deleted.")
            if not confirmed:
                return
            payload["confirmed"] = True
        result = self.service.dispatch(ApplicationIntent(action, payload))
        self.show("Connections & Pools")
        self._set_status(result)

    def _show_connection_operation(self, parent: Any, data: Mapping[str, Any]) -> None:
        if "imported_count" in data:
            provider = str(data.get("provider", ""))
            status = str(data.get("result_status", ""))
            summary = (
                f"{provider}: imported={data.get('imported_count', 0)} | "
                f"already present={data.get('already_present_count', 0)} | "
                f"rejected={data.get('rejected_count', 0)} | "
                f"persistence={data.get('persistence_status', 'UNKNOWN')}"
            )
            if status == "NO_CHANGES":
                summary = f"{provider}: NO CHANGES | already present={data.get('already_present_count', 0)}"
            self.ttk.Label(parent, text=summary, style="Status.TLabel").pack(side="left", padx=(12, 0))
            palette = self.palette[self.dark]
            self.status.configure(text=summary, foreground=palette["good"] if status != "ERROR" else palette["bad"])
        else:
            self._set_status(ApplicationResult(str(data.get("result_status", "OK")), data), str(data.get("status", "Updated")))


def main() -> int:
    ConnectionControlCenterApp().run()
    return 0
