from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from application_boundary import ApplicationIntent, ApplicationResult
from connection_manager import LIFECYCLE_REMOVED, load_registry


_INSTALLED = "_connections_view_runtime_installed"
STABLE_GROQ_IDS = tuple(f"GROQ-{number:02d}" for number in range(1, 16))

_HEADERS = {
    "id": "Connection ID",
    "provider": "Provider",
    "model": "Model",
    "assignment": "Assignment",
    "status": "Status",
    "ready": "Readiness",
    "health": "Health",
    "fingerprint": "Fingerprint",
    "credential": "Credential",
    "reason": "Reason",
    "expiry": "Expiry",
}

_WIDTHS = {
    "id": 108,
    "provider": 92,
    "model": 230,
    "assignment": 125,
    "status": 88,
    "ready": 105,
    "health": 110,
    "fingerprint": 90,
    "credential": 95,
    "reason": 250,
    "expiry": 120,
}


def _natural_id(value: Any) -> tuple[int, str]:
    text = str(value)
    try:
        return (int(text.rsplit("-", 1)[1]), text)
    except (IndexError, ValueError):
        return (10**9, text)


def _expiry(item: Mapping[str, Any]) -> str:
    for key in ("credential_expires_at", "expires_at", "expiry", "expiration"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return "NOT PROVIDED"


def _connection_sort_key(item: Mapping[str, Any]) -> tuple[int, str, tuple[int, str]]:
    configured = 0 if bool(item.get("configured")) else 1
    provider = str(item.get("provider", ""))
    return (configured, provider, _natural_id(item.get("connection_id", "")))


def _fit_tree(tree: Any) -> None:
    """Scale table columns without hiding headings; horizontal scrolling remains available."""
    try:
        tree.update_idletasks()
        viewport = max(int(tree.winfo_width()) - 4, 1)
        columns = list(tree["columns"])
        total = sum(_WIDTHS.get(column, 100) for column in columns)
        if total <= viewport:
            for column in columns:
                tree.column(column, width=_WIDTHS.get(column, 100), minwidth=68, stretch=False)
            return
        scale = viewport / total
        widths = {column: max(72, int(_WIDTHS.get(column, 100) * scale)) for column in columns}
        if sum(widths.values()) > viewport:
            ordered = sorted(columns, key=lambda column: widths[column], reverse=True)
            index = 0
            while sum(widths.values()) > viewport:
                column = ordered[index % len(ordered)]
                if widths[column] > 72:
                    widths[column] -= 1
                index += 1
                if index > 10000:
                    break
        for column in columns:
            tree.column(column, width=widths[column], minwidth=68, stretch=False)
    except Exception:
        pass


def _render(app: Any) -> None:
    if hasattr(app, "_scroll_canvas"):
        try:
            app._scroll_canvas.yview_moveto(0.0)
        except Exception:
            pass

    app._header(
        "Connections & Pools",
        "Stable IDs first. Import status is visible in the table; no new connection IDs are created by the Groq import flow.",
        action=lambda: app.show("Connections & Pools"),
        action_text="Refresh",
    )

    result = app.service.dispatch(ApplicationIntent("refresh_connections", {}))
    connections = result.data.get("connections", []) if isinstance(result.data, Mapping) else []
    items = [item for item in connections if isinstance(item, Mapping)]
    items.sort(key=_connection_sort_key)

    configured = [item for item in items if bool(item.get("configured"))]
    groq_configured = [item for item in configured if str(item.get("provider", "")).lower() == "groq"]
    groq_protected = sum(1 for item in groq_configured if bool(item.get("credential_present")))
    groq_ready = sum(1 for item in groq_configured if str(item.get("ready_state", "")) == "READY")

    summary = app.ttk.Frame(app.body)
    summary.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    for column in range(4):
        summary.columnconfigure(column, weight=1)

    def card(column: int, title: str, value: str, detail: str) -> None:
        frame = app.tk.Frame(summary, bg=app.palette[app.dark]["surface"], highlightbackground=app.palette[app.dark]["border"], highlightthickness=1)
        frame.grid(row=0, column=column, sticky="ew", padx=4)
        app.ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor="w", padx=12, pady=(8, 0))
        app.ttk.Label(frame, text=value, style="CardValue.TLabel").pack(anchor="w", padx=12, pady=(0, 0))
        app.ttk.Label(frame, text=detail, style="CardTitle.TLabel").pack(anchor="w", padx=12, pady=(0, 8))

    card(0, "Configured Connections", str(len(configured)), "Authoritative assignments")
    card(1, "Groq Protected", f"{groq_protected}/{len(groq_configured)}", "Credentials present in protected storage")
    card(2, "Groq READY", f"{groq_ready}/{len(groq_configured)}", "Stored + assigned + lifecycle eligible")
    card(3, "Stable Groq IDs", "15", "GROQ-01 through GROQ-15")

    app.body.rowconfigure(1, weight=1)
    app.body.columnconfigure(0, weight=1)

    table_frame = app.ttk.LabelFrame(app.body, text="Connection inventory", padding=4)
    table_frame.grid(row=1, column=0, sticky="nsew")
    table_frame.columnconfigure(0, weight=1)
    table_frame.rowconfigure(0, weight=1)

    tree = app.ttk.Treeview(
        table_frame,
        columns=tuple(_HEADERS),
        show="headings",
        selectmode="browse",
        height=max(8, min(18, len(items) or 8)),
    )
    vertical = app.ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
    horizontal = app.ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)

    for column, label in _HEADERS.items():
        tree.heading(column, text=label)
        tree.column(column, width=_WIDTHS[column], minwidth=68, anchor="w", stretch=False)

    palette = app.palette[app.dark]
    for state, color in (
        ("READY", palette["good"]),
        ("STORED", palette["muted"]),
        ("SETUP", palette["warn"]),
        ("FAILED", palette["bad"]),
        ("REMOVED", palette["muted"]),
    ):
        tree.tag_configure(state, foreground=color)

    registry = load_registry().get("connections", {})
    for item in items:
        connection_id = str(item.get("connection_id", ""))
        metadata = registry.get(connection_id) if isinstance(registry, Mapping) else None
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
        assignments = item.get("assignments")
        assignment = ", ".join(assignments) if isinstance(assignments, list) and assignments else "unassigned"
        reason = str(item.get("ready_reason", ""))
        tree.insert(
            "",
            "end",
            values=(
                connection_id,
                item.get("provider", ""),
                item.get("model", ""),
                assignment,
                display_status,
                ready_label,
                item.get("runtime_status", "UNOBSERVED"),
                "present" if item.get("fingerprint_present") else "absent",
                "present" if item.get("credential_present") else "absent",
                reason,
                _expiry(metadata) if isinstance(metadata, Mapping) else "NOT PROVIDED",
            ),
            tags=(readiness,),
        )

    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    app.connection_tree = tree

    toolbar = app.ttk.Frame(app.body)
    toolbar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
    actions = (
        ("Import OpenRouter TXT", lambda: app._import("openrouter")),
        ("Import Groq TXT", lambda: app._import("groq")),
        ("Verify Groq Readiness", app._verify_groq_readiness),
        ("Replace / Rotate", lambda: app._connection_action("replace_connection_credential")),
        ("Validate", lambda: app._connection_action("validate_connection")),
        ("Disable", lambda: app._connection_action("disable_connection")),
        ("Enable", lambda: app._connection_action("enable_connection")),
        ("Remove", lambda: app._connection_action("remove_connection")),
    )
    for text, command in actions:
        app.ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=(0, 4))

    note = app.ttk.Label(
        app.body,
        text=(
            f"Visible scope: {len(items)} metadata records, {len(configured)} configured by registry. "
            "Groq import maps credentials to existing stable IDs by fingerprint; unmatched credentials are ignored."
        ),
        style="Subtitle.TLabel",
        wraplength=1100,
        justify="left",
    )
    note.grid(row=3, column=0, sticky="ew", pady=(7, 0))

    app.root.update_idletasks()
    _fit_tree(tree)
    app._set_status(result, "Connection registry refreshed")


def install_connections_view_runtime(app_class: type) -> None:
    if getattr(app_class, _INSTALLED, False):
        return

    def connections(self: Any) -> None:
        _render(self)

    app_class._connections = connections
    setattr(app_class, _INSTALLED, True)
