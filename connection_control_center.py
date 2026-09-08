from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from application_boundary import ApplicationIntent, ApplicationResult, ControlCenterService
from connection_manager import (
    LIFECYCLE_ACTIVE,
    LIFECYCLE_DISABLED,
    PROVIDER_PREFIXES,
    disable_connection,
    enable_connection,
    fingerprint,
    get_connection_status,
    import_known_provider_credentials,
    import_provider,
    load_registry,
    mark_connection_failed,
    read_secret_source,
    remove_connection,
    replace_connection_credential,
    validate_connection,
)
from desktop_control_center import ControlCenterApp
from leader_router import LeaderRouter
from protected_secret_store import SecretStore, SecretStoreError, WindowsProtectedSecretStore
from provider_transport import OpenAICompatibleTransport
from worker_router import WorkerRouter


GROQ_STABLE_IMPORT_IDS = ("GROQ-01", "GROQ-02")


class ConnectionControlCenterService(ControlCenterService):
    """Protected connection lifecycle boundary over the existing Core routers."""

    def __init__(self, *, secret_store: SecretStore | None = None, **kwargs: Any) -> None:
        self.secret_store = secret_store or WindowsProtectedSecretStore()
        self.last_connection_operation: Mapping[str, Any] | None = None
        kwargs.setdefault("leader_transport", OpenAICompatibleTransport(secret_store=self.secret_store))
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
                    if not isinstance(item, Mapping) or item.get("runtime_status") != "FAILED":
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
                    return ApplicationResult(refreshed.status, dict(refreshed.data), refreshed.error)
            return result

        handler = {
            "import_provider_connections": self._import_provider_connections,
            "verify_provider_readiness": self._verify_provider_readiness,
            "replace_connection_credential": self._replace_connection_credential,
            "validate_connection": self._validate_connection,
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
        prefix = PROVIDER_PREFIXES[provider]
        if provider == "groq":
            summary = import_known_provider_credentials(
                provider,
                path,
                registry,
                prefix,
                GROQ_STABLE_IMPORT_IDS,
                secret_store=self.secret_store,
            )
        else:
            summary = import_provider(
                provider,
                path,
                registry,
                prefix,
                secret_store=self.secret_store,
            )
        self._reload_router_state()
        if summary.imported_count == 0 and summary.rejected_count == 0:
            status = "NO_CHANGES"
        elif summary.rejected_count > 0 and summary.imported_count == 0:
            status = "REJECTED"
        else:
            status = "OK"
        return ApplicationResult(status, summary.to_dict())

    def _verify_provider_readiness(self, payload: Mapping[str, Any]) -> ApplicationResult:
        provider = payload.get("provider")
        connection_ids = payload.get("connection_ids")
        if provider != "groq":
            return ApplicationResult("REJECTED", {}, "provider must be groq")
        ids = tuple(connection_ids) if isinstance(connection_ids, (list, tuple)) else GROQ_STABLE_IMPORT_IDS
        if not ids or any(not isinstance(item, str) or not item.strip() for item in ids):
            return ApplicationResult("REJECTED", {}, "connection_ids must contain valid IDs")
        registry = load_registry().get("connections", {})
        results: list[dict[str, Any]] = []
        all_ready = True
        for connection_id in ids:
            item = registry.get(connection_id) if isinstance(registry, Mapping) else None
            if not isinstance(item, Mapping) or item.get("provider") != provider:
                results.append({"connection_id": connection_id, "state": "NOT_READY", "reason": "CONNECTION_ID_MISMATCH"})
                all_ready = False
                continue
            expected = item.get("key_fingerprint")
            if not isinstance(expected, str) or not expected:
                results.append({"connection_id": connection_id, "state": "NOT_READY", "reason": "FINGERPRINT_MISSING"})
                all_ready = False
                continue
            try:
                secret = self.secret_store.get(connection_id, provider)
            except SecretStoreError:
                results.append({"connection_id": connection_id, "state": "NOT_READY", "reason": "SECRET_RECORD_MISSING"})
                all_ready = False
                continue
            if not isinstance(secret, str) or not secret:
                results.append({"connection_id": connection_id, "state": "NOT_READY", "reason": "SECRET_RECORD_INVALID"})
                all_ready = False
                continue
            if fingerprint(secret) != expected:
                results.append({"connection_id": connection_id, "state": "NOT_READY", "reason": "FINGERPRINT_MISMATCH"})
                all_ready = False
                continue
            results.append({"connection_id": connection_id, "state": "READY", "reason": "PROTECTED_CREDENTIAL_RETRIEVABLE"})
        return ApplicationResult(
            "OK" if all_ready else "FAILED",
            {
                "provider": provider,
                "connections": results,
                "all_ready": all_ready,
                "raw_credentials_returned": False,
                "routing_mutated": False,
                "activation_mutated": False,
            },
        )

    def _replace_connection_credential(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id = payload.get("connection_id")
        source_path = payload.get("source_path")
        if not isinstance(connection_id, str) or not connection_id.strip():
            return ApplicationResult("REJECTED", {}, "connection_id is required")
        if not isinstance(source_path, str) or not source_path.strip():
            return ApplicationResult("REJECTED", {}, "Replacement TXT source is required")
        path = Path(source_path).expanduser().resolve()
        if path.suffix.lower() != ".txt" or not path.is_file():
            return ApplicationResult("REJECTED", {}, "Selected replacement source must be an existing .txt file")
        registry = load_registry()
        summary = replace_connection_credential(connection_id, path, registry, secret_store=self.secret_store)
        self._reload_router_state()
        status = "NO_CHANGES" if summary.imported_count == 0 and summary.rejected_count == 0 else "OK"
        return ApplicationResult(status, summary.to_dict())

    def _validate_connection(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, _, registry = self._connection_from_payload(payload)
        try:
            item = validate_connection(connection_id, registry=registry, secret_store=self.secret_store)
        except Exception as exc:
            safe_reason = f"{type(exc).__name__}: {exc}"[:240]
            try:
                failed_registry = load_registry()
                mark_connection_failed(connection_id, reason=safe_reason, registry=failed_registry)
            except Exception:
                pass
            self._reload_router_state()
            return ApplicationResult(
                "FAILED",
                {"connection_id": connection_id, "status": get_connection_status(connection_id, registry)},
                safe_reason,
            )
        self._reload_router_state()
        return ApplicationResult("OK", {"connection_id": connection_id, "status": item["status"], "credential_validated": True})

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
                    "setup_required": "VALIDATION_OR_REGISTRY_ASSIGNMENT",
                },
                str(exc),
            )
        self._reload_router_state()
        return ApplicationResult("OK", {"connection_id": connection_id, "status": result["status"]})

    def _remove_connection(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, _, registry = self._connection_from_payload(payload)
        if payload.get("confirmed") is not True:
            return ApplicationResult("REJECTED", {"connection_id": connection_id}, "Explicit confirmation is required")
        try:
            remove_connection(connection_id, registry=registry, secret_store=self.secret_store)
        except ValueError as exc:
            return ApplicationResult(
                "BLOCKED",
                {"connection_id": connection_id, "status": get_connection_status(connection_id, registry)},
                str(exc),
            )
        self._reload_router_state()
        return ApplicationResult("OK", {"connection_id": connection_id, "status": "REMOVED"})

    def _mark_connection_failed(self, payload: Mapping[str, Any]) -> ApplicationResult:
        connection_id, _, registry = self._connection_from_payload(payload)
        invalid = bool(payload.get("invalid"))
        reason = payload.get("reason")
        safe_reason = reason[:240] if isinstance(reason, str) else None
        result = mark_connection_failed(connection_id, invalid=invalid, reason=safe_reason, registry=registry)
        self._reload_router_state()
        return ApplicationResult(
            "OK",
            {"connection_id": connection_id, "status": result["status"], "reason": result.get("failure_reason", "")},
        )


class ConnectionControlCenterApp(ControlCenterApp):
    """Same Control Center shell with protected connection lifecycle and recovery actions."""

    def __init__(self) -> None:
        super().__init__(service=ConnectionControlCenterService())
        self.connection_tree: Any | None = None

    def _connections(self) -> None:
        self._header(
            "Connections & Pools",
            "✓ READY = securely stored + assigned + validated. New connections remain STORED until explicit admission.",
            action=lambda: self.show("Connections & Pools"),
            action_text="Refresh",
        )
        result = self.service.dispatch(ApplicationIntent("refresh_connections", {}))
        self.body.rowconfigure(0, weight=1)
        tree = self.ttk.Treeview(
            self.body,
            columns=("id", "provider", "model", "assignment", "status", "ready", "runtime", "fingerprint", "credential", "reason"),
            show="headings",
            selectmode="browse",
        )
        labels = {
            "id": "Connection ID", "provider": "Provider", "model": "Model", "assignment": "Assignment",
            "status": "Lifecycle", "ready": "Ready State", "runtime": "Runtime / Health", "fingerprint": "Fingerprint",
            "credential": "Credential", "reason": "Reason",
        }
        widths = {
            "id": 110, "provider": 95, "model": 220, "assignment": 145, "status": 90, "ready": 110,
            "runtime": 115, "fingerprint": 85, "credential": 85, "reason": 260,
        }
        for column in tree["columns"]:
            tree.heading(column, text=labels[column])
            tree.column(column, width=widths[column], anchor="w")
        connections = result.data.get("connections", []) if isinstance(result.data, Mapping) else []
        palette = self.palette[self.dark]
        for state, color in (
            ("READY", palette["good"]),
            ("STORED", palette["muted"]),
            ("SETUP", palette["warn"]),
            ("FAILED", palette["bad"]),
            ("REMOVED", palette["muted"]),
        ):
            tree.tag_configure(state, foreground=color)
        for item in connections:
            item = self._mapping(item)
            readiness = str(item.get("ready_state", "SETUP")).upper()
            if readiness not in {"READY", "STORED", "SETUP", "FAILED", "REMOVED"}:
                readiness = "SETUP"
            ready_label = {
                "READY": "✓ READY",
                "STORED": "● STORED",
                "SETUP": "⚠ SETUP",
                "FAILED": "✕ FAILED",
                "REMOVED": "— REMOVED",
            }[readiness]
            raw_status = str(item.get("metadata_status", "UNKNOWN"))
            display_status = "ACTIVE" if raw_status == "VALIDATED" else raw_status
            assignment = ", ".join(item.get("assignments", [])) if isinstance(item.get("assignments"), list) else "unassigned"
            reason = str(item.get("ready_reason", ""))
            tree.insert(
                "",
                "end",
                values=(
                    item.get("connection_id", ""), item.get("provider", ""), item.get("model", ""), assignment,
                    display_status, ready_label, item.get("runtime_status", "UNOBSERVED"),
                    "present" if item.get("fingerprint_present") else "absent",
                    "present" if item.get("credential_present") else "absent", reason,
                ),
                tags=(readiness,),
            )
        tree.grid(row=0, column=0, sticky="nsew")
        self.connection_tree = tree

        toolbar = self.ttk.Frame(self.body)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for provider, label in (("openrouter", "Import OpenRouter TXT"), ("groq", "Import Groq TXT")):
            self.ttk.Button(toolbar, text=label, command=lambda p=provider: self._import(p)).pack(side="left", padx=(0, 5))
        self.ttk.Button(toolbar, text="Verify Groq Readiness", command=self._verify_groq_readiness).pack(side="left", padx=(0, 5))
        for action, label in (
            ("replace_connection_credential", "Replace / Rotate"),
            ("validate_connection", "Validate"),
            ("disable_connection", "Disable"),
            ("enable_connection", "Enable"),
            ("remove_connection", "Remove"),
        ):
            self.ttk.Button(toolbar, text=label, command=lambda a=action: self._connection_action(a)).pack(side="left", padx=(0, 5))
        legend = self.ttk.Label(
            toolbar,
            text="✓ READY = stored + assigned + validated | ● STORED = saved, not routed | ⚠ SETUP = needs attention | ✕ FAILED = unavailable",
            style="Status.TLabel",
        )
        legend.pack(side="left", padx=(6, 0))
        operation = getattr(self.service, "last_connection_operation", None)
        if isinstance(operation, Mapping):
            self._show_connection_operation(toolbar, operation)
        else:
            self._set_status(result, "Connection registry refreshed")

    def _selected_connection_id(self) -> str | None:
        if self.connection_tree is None:
            return None
        selection = self.connection_tree.selection()
        if not selection:
            return None
        values = self.connection_tree.item(selection[0], "values")
        return str(values[0]) if values else None

    def _import(self, provider: str) -> None:
        from tkinter import filedialog, messagebox
        path = filedialog.askopenfilename(
            title=f"Import {provider} TXT source",
            filetypes=[("Text files", "*.txt")],
        )
        if not path:
            return
        source = Path(path).resolve()
        if provider == "groq":
            self._groq_import_preview(source)
            return
        result = self.service.dispatch(
            ApplicationIntent("import_provider_connections", {"provider": provider, "source_path": str(source)})
        )
        self.show("Connections & Pools")
        self._set_status(result)

    def _groq_import_preview(self, source: Path) -> None:
        from tkinter import messagebox
        try:
            labeled, unlabeled = read_secret_source(source, PROVIDER_PREFIXES["groq"])
        except Exception as exc:
            messagebox.showerror("Groq import", f"Cannot read TXT source: {type(exc).__name__}: {exc}")
            return

        registry = load_registry().get("connections", {})
        known_by_fingerprint: dict[str, str] = {}
        for connection_id in GROQ_STABLE_IMPORT_IDS:
            item = registry.get(connection_id) if isinstance(registry, Mapping) else None
            if isinstance(item, Mapping) and isinstance(item.get("key_fingerprint"), str):
                known_by_fingerprint[item["key_fingerprint"]] = connection_id

        known_matches: list[str] = []
        for secret in unlabeled:
            connection_id = known_by_fingerprint.get(fingerprint(secret))
            if connection_id and connection_id not in known_matches:
                known_matches.append(connection_id)

        labeled_targets = sorted(set(labeled) & set(GROQ_STABLE_IMPORT_IDS))
        unexpected_labeled = sorted(set(labeled) - set(GROQ_STABLE_IMPORT_IDS))
        summary = [
            "SAFE GROQ IMPORT PREVIEW",
            "",
            f"Source: {source}",
            f"Total source entries: {len(labeled) + len(unlabeled)}",
            f"Explicit GROQ IDs: {', '.join(labeled_targets) if labeled_targets else '(none)'}",
            f"Unlabeled entries: {len(unlabeled)}",
            f"Known stable matches: {', '.join(sorted(known_matches)) if known_matches else '(none)'}",
            f"Unmatched entries: {max(0, len(unlabeled) - len(known_matches))}",
            f"Unexpected explicit IDs: {', '.join(unexpected_labeled) if unexpected_labeled else '(none)'}",
            "",
            "Credential values are never displayed.",
            "Only existing stable GROQ-01 / GROQ-02 identities can be imported.",
            "No new Groq connection IDs will be created by this flow.",
        ]
        proceed = bool(known_matches or labeled_targets) and not unexpected_labeled
        if not proceed:
            messagebox.showwarning("Groq import blocked", "\n".join(summary) + "\n\nNo known stable Groq credential was found.")
            return
        proceed = messagebox.askyesno("Confirm Groq import", "\n".join(summary) + "\n\nImport matching stable credentials into protected storage?")
        if not proceed:
            return
        result = self.service.dispatch(
            ApplicationIntent("import_provider_connections", {"provider": "groq", "source_path": str(source)})
        )
        self.show("Connections & Pools")
        self._set_status(result)

    def _verify_groq_readiness(self) -> None:
        result = self.service.dispatch(
            ApplicationIntent("verify_provider_readiness", {"provider": "groq", "connection_ids": list(GROQ_STABLE_IMPORT_IDS)})
        )
        self.show("Connections & Pools")
        lines: list[str] = ["GROQ PROTECTED-CREDENTIAL READINESS", ""]
        items = result.data.get("connections", []) if isinstance(result.data, Mapping) else []
        for item in items:
            item = self._mapping(item)
            lines.append(f"{item.get('connection_id', '?')} = {item.get('state', 'UNRESOLVED')} — {item.get('reason', '')}")
        lines.extend([
            "",
            "Credential values displayed: NO",
            "Routing mutated: NO",
            "Activation mutated: NO",
        ])
        from tkinter import messagebox
        if result.status == "OK":
            messagebox.showinfo("Groq readiness", "\n".join(lines))
        else:
            messagebox.showwarning("Groq readiness", "\n".join(lines))
        self._set_status(result, "Groq protected-credential readiness checked")

    def _connection_action(self, action: str) -> None:
        from tkinter import filedialog, messagebox
        connection_id = self._selected_connection_id()
        if not connection_id:
            self._set_status(ApplicationResult("REJECTED", {}, "Select a connection first"))
            return
        payload: dict[str, Any] = {"connection_id": connection_id}
        if action == "replace_connection_credential":
            path = filedialog.askopenfilename(
                title=f"Replace credential for {connection_id}",
                filetypes=[("Text files", "*.txt")],
            )
            if not path:
                return
            payload["source_path"] = path
        elif action == "remove_connection":
            confirmed = messagebox.askyesno(
                "Remove connection",
                f"Remove {connection_id}? The protected credential will be deleted.",
            )
            if not confirmed:
                return
            payload["confirmed"] = True
        result = self.service.dispatch(ApplicationIntent(action, payload))
        self.show("Connections & Pools")
        self._set_status(result)

    def _show_connection_operation(self, parent: Any, data: Mapping[str, Any]) -> None:
        provider = str(data.get("provider", ""))
        status = str(data.get("result_status", ""))
        ids = data.get("connection_ids", [])
        affected = f" | ids={', '.join(str(x) for x in ids)}" if isinstance(ids, list) and ids else ""
        if "imported_count" in data:
            summary = (
                f"{provider}: imported={data.get('imported_count', 0)} | "
                f"already present={data.get('already_present_count', 0)} | "
                f"rejected={data.get('rejected_count', 0)} | "
                f"unmatched={data.get('unmatched_count', 0)} | "
                f"persistence={data.get('persistence_status', 'UNKNOWN')}{affected}"
            )
            if status == "NO_CHANGES":
                summary = f"{provider}: NO CHANGES | already present={data.get('already_present_count', 0)} | unmatched={data.get('unmatched_count', 0)}{affected}"
            self.ttk.Label(parent, text=summary, style="Status.TLabel").pack(side="left", padx=(8, 0))
            palette = self.palette[self.dark]
            self.status.configure(
                text=summary,
                foreground=palette["good"] if status not in {"ERROR", "FAILED", "REJECTED"} else palette["bad"],
            )
        else:
            self._set_status(ApplicationResult(status or "OK", data), str(data.get("status", "Updated")))


def main() -> int:
    ConnectionControlCenterApp().run()
    return 0
