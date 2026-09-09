from __future__ import annotations

from collections.abc import Mapping
from typing import Any


ROUTER_MODELS_PAGE = "Router Models"


def _fit_tree(tree: Any) -> None:
    try:
        tree.update_idletasks()
        columns = list(tree["columns"])
        if not columns:
            return
        viewport = max(int(tree.winfo_width()) - 6, 1)
        widths = {column: int(tree.column(column, "width")) for column in columns}
        total = sum(widths.values())
        if total <= viewport:
            return
        scale = viewport / total
        for column in columns:
            tree.column(column, width=max(68, int(widths[column] * scale)), minwidth=68, stretch=False)
    except Exception:
        pass


def _router_models(self: Any) -> None:
    self._header(
        ROUTER_MODELS_PAGE,
        "Authoritative routing models come from the existing Core registry; this view does not mutate routing.",
        action=lambda: self.show(ROUTER_MODELS_PAGE),
        action_text="Refresh",
    )
    tree = self.ttk.Treeview(self.body, columns=("router", "tier", "model", "configured", "healthy", "failed"), show="headings")
    labels = {"router":"Router","tier":"Tier / Role","model":"Configured Model","configured":"Configured Pool","healthy":"External Healthy","failed":"Runtime / External Failed"}
    widths = {"router":120,"tier":125,"model":300,"configured":210,"healthy":110,"failed":150}
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
        healthy = getattr(leader, "external_healthy_by_model", {})
        failed = getattr(leader, "external_failed_by_model", {})
        tree.insert("", "end", values=("Leader Router", "Primary / ULTRA", primary_model, ", ".join(primary_pool), len(healthy.get(primary_model, set())), len(failed.get(primary_model, set()))))
        tree.insert("", "end", values=("Leader Router", "Failover / SUPER", failover_model, ", ".join(failover_pool), len(healthy.get(failover_model, set())), len(failed.get(failover_model, set()))))
    if worker is not None:
        model = str(getattr(worker, "model", ""))
        pools = getattr(worker, "worker_pools", {})
        healthy_connections = set(getattr(worker, "external_healthy_connections", set()))
        failed_connections = set(getattr(worker, "external_failed_connections", set())) | set(getattr(worker, "runtime_failed_connections", set()))
        for role, pool in pools.items():
            pool_ids = list(pool) if isinstance(pool, (list, tuple, set)) else []
            tree.insert("", "end", values=("Worker Router", str(role), model, ", ".join(map(str, pool_ids)), len(set(pool_ids) & healthy_connections), len(set(pool_ids) & failed_connections)))
    tree.grid(row=0, column=0, sticky="nsew")
    self._set_status(ApplicationResultShim("OK"), "Router models refreshed")
    _fit_tree(tree)


class ApplicationResultShim:
    error = None
    status = "OK"


def _install_tree_fit(app_class: type) -> None:
    original_show = app_class.show
    if getattr(original_show, "_tree_fit_runtime_wrapped", False):
        return

    def show(self: Any, page: str) -> None:
        original_show(self, page)
        self.root.update_idletasks()
        for widget in self.body.winfo_children():
            _fit_descendant_trees(self, widget)

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


def install_operator_runtime(app_class: type) -> None:
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
