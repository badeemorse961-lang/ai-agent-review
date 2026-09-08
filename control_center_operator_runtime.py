from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from connection_manager import load_registry


ROUTER_MODELS_PAGE = "Router Models"

_CONNECTION_HEADERS = {
    "id": "Connection ID",
    "provider": "Provider",
    "model": "Model",
    "assignment": "Assignment",
    "status": "Status",
    "ready": "Readiness",
    "runtime": "Health",
    "fingerprint": "Fingerprint",
    "credential": "Credential",
    "reason": "Reason",
    "expiry": "Expiry",
}

_CONNECTION_WIDTHS = {
    "id": 95,
    "provider": 70,
    "model": 185,
    "assignment": 105,
    "status": 75,
    "ready": 90,
    "runtime": 85,
    "fingerprint": 90,
    "credential": 90,
    "reason": 135,
    "expiry": 105,
}


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
        if "expiry" not in columns:
            columns.append("expiry")
            tree["columns"] = tuple(columns)

        # Re-apply all headings after extending the Treeview columns. ttk can
        # reset existing heading configuration when the columns tuple changes.
        for column in columns:
            tree.heading(column, text=_CONNECTION_HEADERS.get(column, column))
            tree.column(
                column,
                width=_CONNECTION_WIDTHS.get(column, 100),
                minwidth=68,
                anchor="w",
                stretch=False,
            )

        registry = load_registry()
        connections = registry.get("connections", {})
        for row_id in tree.get_children(""):
            values = list(tree.item(row_id, "values"))
            connection_id = str(values[0]) if values else ""
            item = connections.get(connection_id) if isinstance(connections, Mapping) else None
            expiry = _expiry_label(item) if isinstance(item, Mapping) else "NOT PROVIDED"
            if len(values) < len(columns):
                values.append(expiry)
            else:
                values[-1] = expiry
            tree.item(row_id, values=tuple(values))
        _fit_tree(tree)

    wrapped._expiry_runtime_wrapped = True
    app_class._connections = wrapped


def _fit_tree(tree: Any) -> None:
    """Keep the main tree usable within the current viewport; no clipped right-side columns."""
    try:
        tree.update_idletasks()
        viewport = max(int(tree.winfo_width()) - 6, 1)
        columns = list(tree["columns"])
        if not columns:
            return
        if not hasattr(tree, "_base_tree_widths"):
            tree._base_tree_widths = {column: int(tree.column(column, "width")) for column in columns}
        base = dict(tree._base_tree_widths)
        total = sum(base.get(column, 80) for column in columns)
        if total <= viewport:
            return
        scale = viewport / total
        widths: dict[str, int] = {column: max(68, int(base.get(column, 80) * scale)) for column in columns}
        total_scaled = sum(widths.values())
        if total_scaled > viewport:
            order = sorted(columns, key=lambda column: widths[column], reverse=True)
            index = 0
            while total_scaled > viewport and order:
                column = order[index % len(order)]
                if widths[column] > 68:
                    widths[column] -= 1
                    total_scaled -= 1
                index += 1
        for column in columns:
            tree.column(column, width=widths[column], minwidth=min(widths[column], 68), stretch=False)
    except Exception:
        pass


def _install_tree_fit(app_class: type) -> None:
    original_show = app_class.show
    if getattr(original_show, "_tree_fit_runtime_wrapped", False):
        return

    def _fit_current(self: Any) -> None:
        try:
            for item in self.body.winfo_children():
                _fit_descendant_trees(self, item)
        except Exception:
            pass

    def show(self: Any, page: str) -> None:
        original_show(self, page)
        self.root.update_idletasks()
        _fit_current(self)

    show._tree_fit_runtime_wrapped = True
    app_class.show = show


def _fit_descendant_trees(app: Any, widget: Any) -> None:
    try:
        if isinstance(widget, app.ttk.Treeview):
            _fit_tree(widget)
        for child in widget.winfo_children():
            _fit_descendant_trees(app, child)
    except Exception:
        pass


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
    widths = {"router": 120, "tier": 125, "model": 300, "configured": 210, "healthy": 110, "failed": 150}
    for column in tree["columns"]:
        tree.heading(column, text=labels[column])
        tree.column(column, width=widths[column], minwidth=68, anchor="w", stretch=False)

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
        text="This page reports configured routing models only. It does not enumerate every model offered by Groq/OpenRouter and does not mutate routing. Credential expiry is shown in Connections & Pools only when explicit metadata provides it.",
        style="Subtitle.TLabel",
        wraplength=1050,
        justify="left",
    )
    note.grid(row=1, column=0, sticky="ew", pady=(10, 0))
    self._set_status(type("Result", (), {"error": None, "status": "OK"})(), "Router models refreshed")
    _fit_tree(tree)


def install_operator_runtime(app_class: type) -> None:
    _install_expiry_column(app_class)
    _install_tree_fit(app_class)
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
            self.root.update_idletasks()
            return
        original_show(self, page)
        self.root.update_idletasks()

    show._router_runtime_wrapped = True
    app_class.show = show
    navigation = list(getattr(app_class, "NAVIGATION", ()))
    if not any(label == ROUTER_MODELS_PAGE for label, _ in navigation):
        insert_at = next((i for i, (label, _) in enumerate(navigation) if label == "Workers"), len(navigation))
        navigation.insert(insert_at, (ROUTER_MODELS_PAGE, ROUTER_MODELS_PAGE))
        app_class.NAVIGATION = tuple(navigation)
