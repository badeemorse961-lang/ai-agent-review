from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from connection_manager import load_registry


ROUTER_MODELS_PAGE = "Router Models"


def _expiry_label(item: Mapping[str, Any]) -> str:
    for key in ("credential_expires_at", "expires_at", "expiry", "expiration"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return "NOT PROVIDED"


def _install_expiry_column(app_class: type) -> None:
    original = app_class._connections
    if getattr(original, "_expiry_runtime_wrapped", False):
        return

    def wrapped(self: Any) -> None:
        original(self)
        tree = getattr(self, "connection_tree", None)
        if tree is None:
            return
        columns = list(tree["columns"])
        if "expiry" in columns:
            return
        columns.append("expiry")
        tree["columns"] = tuple(columns)
        tree.heading("expiry", text="Expiry")
        tree.column("expiry", width=130, anchor="w")
        registry = load_registry()
        connections = registry.get("connections", {})
        for row_id in tree.get_children(""):
            values = list(tree.item(row_id, "values"))
            connection_id = str(values[0]) if values else ""
            item = connections.get(connection_id) if isinstance(connections, Mapping) else None
            values.append(_expiry_label(item) if isinstance(item, Mapping) else "NOT PROVIDED")
            tree.item(row_id, values=tuple(values))

    wrapped._expiry_runtime_wrapped = True
    app_class._connections = wrapped


def _router_models(self: Any) -> None:
    self._header(
        "Router Models",
        "Authoritative models come only from config/registry.json; provider model discovery never changes routing automatically.",
        action=lambda: self.show(ROUTER_MODELS_PAGE),
        action_text="Refresh",
    )
    body = self.body
    body.rowconfigure(0, weight=1)
    tree = self.ttk.Treeview(
        body,
        columns=("router", "tier", "model", "configured", "healthy", "failed"),
        show="headings",
    )
    labels = {
        "router": "Router",
        "tier": "Tier / Role",
        "model": "Configured Model",
        "configured": "Configured Pool",
        "healthy": "External Healthy",
        "failed": "Runtime / External Failed",
    }
    widths = {"router": 130, "tier": 140, "model": 330, "configured": 220, "healthy": 150, "failed": 180}
    for column in tree["columns"]:
        tree.heading(column, text=labels[column])
        tree.column(column, width=widths[column], anchor="w")

    service = self.service
    leader = getattr(service, "leader_router", None)
    worker = getattr(service, "worker_router", None)
    if leader is not None:
        primary_model = str(getattr(leader, "primary_model", ""))
        failover_model = str(getattr(leader, "failover_model", ""))
        primary_pool = list(getattr(leader, "primary_pool", []))
        failover_pool = list(getattr(leader, "failover_pool", []))
        healthy_by_model = getattr(leader, "external_healthy_by_model", {})
        failed_by_model = getattr(leader, "external_failed_by_model", {})
        tree.insert("", "end", values=("Leader Router", "Primary / ULTRA", primary_model, ", ".join(primary_pool), len(healthy_by_model.get(primary_model, set())), len(failed_by_model.get(primary_model, set()))))
        tree.insert("", "end", values=("Leader Router", "Failover / SUPER", failover_model, ", ".join(failover_pool), len(healthy_by_model.get(failover_model, set())), len(failed_by_model.get(failover_model, set()))))

    if worker is not None:
        model = str(getattr(worker, "model", ""))
        pools = getattr(worker, "worker_pools", {})
        healthy = set(getattr(worker, "external_healthy_connections", set()))
        failed = set(getattr(worker, "external_failed_connections", set())) | set(getattr(worker, "runtime_failed_connections", set()))
        for role, pool in pools.items():
            tree.insert("", "end", values=("Worker Router", role, model, ", ".join(pool), len(set(pool) & healthy), len(set(pool) & failed)))

    tree.grid(row=0, column=0, sticky="nsew")
    note = self.ttk.Label(
        body,
        text="This page reports configured routing models only. It does not enumerate every model offered by Groq/OpenRouter and does not mutate routing.",
        style="Subtitle.TLabel",
        wraplength=1050,
        justify="left",
    )
    note.grid(row=1, column=0, sticky="ew", pady=(10, 0))
    self._set_status(type("Result", (), {"error": None, "status": "OK"})(), "Router models refreshed")


def install_operator_runtime(app_class: type) -> None:
    _install_expiry_column(app_class)
    if not hasattr(app_class, "_router_models"):
        app_class._router_models = _router_models
    original_show = app_class.show
    if getattr(original_show, "_router_runtime_wrapped", False):
        return

    def show(self: Any, page: str) -> None:
        if page == ROUTER_MODELS_PAGE:
            self.current_page = page
            self._clear()
            self._router_models()
            return
        original_show(self, page)

    show._router_runtime_wrapped = True
    app_class.show = show
    navigation = list(getattr(app_class, "NAVIGATION", ()))
    if not any(label == ROUTER_MODELS_PAGE for label, _ in navigation):
        insert_at = next((i for i, (label, _) in enumerate(navigation) if label == "Workers"), len(navigation))
        navigation.insert(insert_at, (ROUTER_MODELS_PAGE, ROUTER_MODELS_PAGE))
        app_class.NAVIGATION = tuple(navigation)
