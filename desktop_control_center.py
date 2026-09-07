from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any

from application_boundary import ApplicationIntent, ApplicationResult, ControlCenterService


class ControlCenterApp:
    """Professional Windows desktop surface over the existing Core.

    Presentation and operator intent only. Routing, validation, authorization,
    execution, sandboxing, and mutation remain owned by the Core.
    """

    NAVIGATION = (
        ("Dashboard", "Overview"),
        ("Chat", "Leader"),
        ("Projects", "Workspace"),
        ("Connections & Pools", "Connections"),
        ("Workers", "Fleet"),
        ("Run / Plan", "Run"),
        ("Evidence & Activity", "Evidence"),
        ("Git & Changes", "Git"),
        ("Tests & Verification", "Tests"),
        ("Safety & Policy", "Safety"),
        ("Settings / Diagnostics", "Settings"),
    )

    def __init__(self, service: ControlCenterService | None = None) -> None:
        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as exc:
            raise RuntimeError("Tkinter is required for the Windows Control Center") from exc
        self.tk, self.ttk = tk, ttk
        self.service = service or ControlCenterService()
        self.root = tk.Tk()
        self.root.title("AI-Agent Control Center")
        self.root.geometry("1380x880")
        self.root.minsize(1120, 720)
        self.dark = True
        self._build_styles()
        self._build_shell()
        self.show("Dashboard")

    def _build_styles(self) -> None:
        style = self.ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        self.palette = {
            True: {
                "bg": "#10151c",
                "surface": "#171e27",
                "surface2": "#202936",
                "fg": "#ecf1f7",
                "muted": "#9eabb9",
                "accent": "#65a9ff",
                "good": "#51d18a",
                "warn": "#e5b65c",
                "bad": "#ef6b73",
                "border": "#2e3948",
            },
            False: {
                "bg": "#f3f6fa",
                "surface": "#ffffff",
                "surface2": "#e9eef5",
                "fg": "#17202b",
                "muted": "#637080",
                "accent": "#276fc2",
                "good": "#188b53",
                "warn": "#9a6b00",
                "bad": "#b3333d",
                "border": "#d1d9e4",
            },
        }
        self._apply_theme()
        style.configure("Treeview", rowheight=30, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", font=("Segoe UI", 10), padding=(11, 8))
        style.configure("Nav.TButton", anchor="w", padding=(13, 10), font=("Segoe UI", 10))
        style.configure("Primary.TButton", font=("Segoe UI", 10, "bold"), padding=(13, 9))
        style.configure("Title.TLabel", font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("CardValue.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Section.TLabel", font=("Segoe UI", 12, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))

    def _apply_theme(self) -> None:
        palette = self.palette[self.dark]
        self.root.configure(background=palette["bg"])
        style = self.ttk.Style(self.root)
        style.configure("TFrame", background=palette["bg"])
        style.configure("TLabel", background=palette["bg"], foreground=palette["fg"])
        style.configure("Title.TLabel", background=palette["bg"], foreground=palette["fg"])
        style.configure("Subtitle.TLabel", background=palette["bg"], foreground=palette["muted"])
        style.configure("CardTitle.TLabel", background=palette["surface"], foreground=palette["muted"])
        style.configure("CardValue.TLabel", background=palette["surface"], foreground=palette["fg"])
        style.configure("Section.TLabel", background=palette["bg"], foreground=palette["fg"])
        style.configure("Status.TLabel", background=palette["bg"], foreground=palette["good"])
        style.configure("Nav.TButton", background=palette["surface"], foreground=palette["fg"])
        style.configure("Primary.TButton", background=palette["accent"], foreground="#ffffff")
        style.configure(
            "Treeview",
            background=palette["surface"],
            fieldbackground=palette["surface"],
            foreground=palette["fg"],
            bordercolor=palette["border"],
        )
        style.configure("Treeview.Heading", background=palette["surface2"], foreground=palette["fg"])
        style.map("Treeview", background=[("selected", palette["accent"])], foreground=[("selected", "#ffffff")])

    def _build_shell(self) -> None:
        ttk = self.ttk
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self.root, padding=14)
        sidebar.grid(row=0, column=0, sticky="ns")
        ttk.Label(sidebar, text="AI-Agent", style="Title.TLabel").pack(anchor="w", pady=(4, 2))
        ttk.Label(sidebar, text="Control Center", style="Subtitle.TLabel").pack(anchor="w", pady=(0, 18))
        for label, command_name in self.NAVIGATION:
            ttk.Button(
                sidebar,
                text=f"  {label}",
                style="Nav.TButton",
                command=lambda name=label: self.show(name),
            ).pack(fill="x", pady=2)
        ttk.Separator(sidebar).pack(fill="x", pady=12)
        self.theme_button = ttk.Button(sidebar, text="  Toggle theme", command=self.toggle_theme)
        self.theme_button.pack(fill="x", pady=2)
        ttk.Button(sidebar, text="  Exit", command=self.root.destroy).pack(fill="x", pady=2)

        main = ttk.Frame(self.root, padding=(12, 14))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        self.header = ttk.Frame(main)
        self.header.grid(row=0, column=0, sticky="ew")
        self.body = ttk.Frame(main)
        self.body.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.status = ttk.Label(main, text="Ready", style="Status.TLabel")
        self.status.grid(row=2, column=0, sticky="ew", pady=(9, 0))

    def toggle_theme(self) -> None:
        self.dark = not self.dark
        self._apply_theme()
        current = getattr(self, "current_page", "Dashboard")
        self.show(current)

    def _header(self, title: str, subtitle: str, *, action: Any | None = None, action_text: str = "") -> None:
        for child in self.header.winfo_children():
            child.destroy()
        self.header.columnconfigure(0, weight=1)
        self.ttk.Label(self.header, text=title, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.ttk.Label(self.header, text=subtitle, style="Subtitle.TLabel").grid(row=1, column=0, sticky="w")
        if action is not None:
            self.ttk.Button(self.header, text=action_text, style="Primary.TButton", command=action).grid(
                row=0, column=1, rowspan=2, sticky="e"
            )

    def _clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()

    def _set_status(self, result: ApplicationResult, success_text: str | None = None) -> None:
        palette = self.palette[self.dark]
        message = result.error or success_text or result.status
        color = palette["bad"] if result.error or result.status in {"ERROR", "REJECTED"} else palette["good"]
        self.status.configure(text=message, foreground=color)

    def _card(self, parent: Any, column: int, title: str, value: str, detail: str = "") -> Any:
        palette = self.palette[self.dark]
        card = self.tk.Frame(parent, bg=palette["surface"], highlightbackground=palette["border"], highlightthickness=1)
        card.grid(row=0, column=column, sticky="nsew", padx=5)
        parent.columnconfigure(column, weight=1)
        self.ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w", padx=14, pady=(12, 0))
        self.ttk.Label(card, text=value, style="CardValue.TLabel").pack(anchor="w", padx=14, pady=(2, 0))
        if detail:
            self.ttk.Label(card, text=detail, style="CardTitle.TLabel").pack(anchor="w", padx=14, pady=(2, 12))
        else:
            self.ttk.Label(card, text=" ", style="CardTitle.TLabel").pack(anchor="w", padx=14, pady=(0, 12))
        return card

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    def show(self, page: str) -> None:
        self.current_page = page
        self._clear()
        pages = {
            "Dashboard": self._dashboard,
            "Chat": self._chat,
            "Projects": self._projects,
            "Connections & Pools": self._connections,
            "Workers": self._workers,
            "Run / Plan": self._run_plan,
            "Evidence & Activity": self._evidence,
            "Git & Changes": self._git,
            "Tests & Verification": self._tests,
            "Safety & Policy": self._safety,
            "Settings / Diagnostics": self._settings,
        }
        pages[page]()

    def _dashboard(self) -> None:
        self._header("Dashboard", "Operational state derived from the Core; no simulated runtime data.")
        result = self.service.dispatch(ApplicationIntent("refresh_dashboard", {}))
        data = self._mapping(result.data)
        self._set_status(result, "Dashboard refreshed")

        cards = self.ttk.Frame(self.body)
        cards.grid(row=0, column=0, sticky="ew")
        for index in range(4):
            cards.columnconfigure(index, weight=1)
        project = self._mapping(data.get("project"))
        leader = self._mapping(data.get("leader"))
        workers = self._mapping(data.get("workers"))
        git = self._mapping(data.get("git"))
        self._card(cards, 0, "Project", str(project.get("state", "NOT SELECTED")), str(project.get("workspace", "Select a workspace")))
        self._card(cards, 1, "Leader", str(leader.get("active_account", leader.get("active_connection", "NOT CONFIGURED"))), str(leader.get("active_tier", "")))
        self._card(cards, 2, "Workers", str(len(workers.get("healthy", []))), f"{len(workers.get('failed', []))} failed")
        self._card(cards, 3, "Git", "CLEAN" if git.get("clean") else "DIRTY", str(git.get("branch", "unavailable")))

        lower = self.ttk.Frame(self.body)
        lower.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        lower.columnconfigure(0, weight=1)
        lower.columnconfigure(1, weight=1)
        lower.rowconfigure(0, weight=1)
        self.body.rowconfigure(1, weight=1)

        recent = self.ttk.LabelFrame(lower, text="Current Run", padding=14)
        recent.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        last_run = self._mapping(data.get("last_run"))
        if last_run:
            self._status_lines(recent, [
                ("Status", str(last_run.get("status", "UNKNOWN"))),
                ("Task", str(last_run.get("task_id", "-"))),
            ])
        else:
            self.ttk.Label(recent, text="No run has been executed in this application session.", style="Subtitle.TLabel").pack(anchor="w", pady=8)

        alerts = self.ttk.LabelFrame(lower, text="Operational Notes", padding=14)
        alerts.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        for text in (
            "UNKNOWN / CONFLICT remain fail-closed.",
            "Git mutation is not exposed by the UI.",
            "Raw provider secrets are never rendered.",
            "Dynamic Connection Onboarding remains configuration-driven only.",
        ):
            self.ttk.Label(alerts, text=f"• {text}", style="Subtitle.TLabel").pack(anchor="w", pady=5)

    def _status_lines(self, parent: Any, lines: list[tuple[str, str]]) -> None:
        for row, (label, value) in enumerate(lines):
            self.ttk.Label(parent, text=label, style="CardTitle.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 24), pady=5)
            self.ttk.Label(parent, text=value, style="Status.TLabel").grid(row=row, column=1, sticky="w", pady=5)

    def _chat(self) -> None:
        self._header("Chat with Central Leader", "Natural-language goals become typed application intents; they are never shell commands.")
        self.body.rowconfigure(1, weight=1)
        form = self.ttk.LabelFrame(self.body, text="New Goal", padding=12)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        self.ttk.Label(form, text="Goal").grid(row=0, column=0, padx=(0, 8))
        goal = self.tk.StringVar()
        entry = self.tk.Entry(form, textvariable=goal)
        entry.grid(row=0, column=1, sticky="ew")
        self.ttk.Label(form, text="Task ID").grid(row=0, column=2, padx=(12, 5))
        task_id = self.tk.StringVar(value="UI-TASK-001")
        self.tk.Entry(form, textvariable=task_id, width=18).grid(row=0, column=3)
        output = self.ttk.LabelFrame(self.body, text="Leader Response", padding=12)
        output.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        output.columnconfigure(0, weight=1)
        output.rowconfigure(0, weight=1)
        text = self.tk.Text(output, wrap="word", font=("Segoe UI", 10), relief="flat")
        text.grid(row=0, column=0, sticky="nsew")
        def send() -> None:
            result = self.service.dispatch(ApplicationIntent("send_leader_goal", {"goal": goal.get(), "task_id": task_id.get()}))
            text.delete("1.0", "end")
            if result.error:
                text.insert("1.0", f"{result.status}: {result.error}")
            else:
                plan = self._mapping(result.data.get("plan"))
                tasks = plan.get("tasks", []) if isinstance(plan.get("tasks"), list) else []
                text.insert("1.0", f"Goal accepted\n\nPlan: {plan.get('goal', 'structured plan')}\nTasks: {len(tasks)}\n\n")
                for item in tasks:
                    task = self._mapping(item)
                    text.insert("end", f"• {task.get('task_id', '?')} — {task.get('objective', '?')}\n")
            self._set_status(result, "Leader plan received")
        self.ttk.Button(form, text="Send Goal", style="Primary.TButton", command=send).grid(row=0, column=4, padx=(10, 0))
        entry.focus_set()

    def _projects(self) -> None:
        self._header("Projects", "Select a bounded workspace; the Core remains responsible for project classification.")
        frame = self.ttk.LabelFrame(self.body, text="Active Workspace", padding=14)
        frame.grid(row=0, column=0, sticky="ew")
        frame.columnconfigure(1, weight=1)
        self.ttk.Label(frame, text="Workspace path").grid(row=0, column=0, padx=(0, 8))
        value = self.tk.StringVar(value=str(self.service.workspace_root or ""))
        self.tk.Entry(frame, textvariable=value).grid(row=0, column=1, sticky="ew")
        def select() -> None:
            from tkinter import filedialog
            path = filedialog.askdirectory(title="Select project workspace")
            if not path:
                return
            result = self.service.dispatch(ApplicationIntent("select_project", {"workspace_root": path}))
            self._set_status(result, "Project selected")
            self.show("Dashboard")
        self.ttk.Button(frame, text="Select", style="Primary.TButton", command=select).grid(row=0, column=2, padx=(10, 0))
        info = self.ttk.LabelFrame(self.body, text="Project State", padding=14)
        info.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        self.body.rowconfigure(1, weight=1)
        self.ttk.Label(info, text="Project state, detected documentation, health, conflicts, and gaps are read from the Core project-understanding pipeline.", style="Subtitle.TLabel", wraplength=800).pack(anchor="w")

    def _connections(self) -> None:
        self._header("Connections & Pools", "Registry assignments are authoritative; runtime health is observational.", action=lambda: self.show("Connections & Pools"), action_text="Refresh")
        result = self.service.dispatch(ApplicationIntent("refresh_connections", {}))
        columns = ("id", "provider", "model", "assignment", "runtime", "metadata", "fingerprint")
        tree = self.ttk.Treeview(self.body, columns=columns, show="headings")
        labels = {
            "id": "Connection ID", "provider": "Provider", "model": "Model", "assignment": "Assignment",
            "runtime": "Runtime", "metadata": "Metadata", "fingerprint": "Fingerprint",
        }
        widths = {"id": 120, "provider": 110, "model": 300, "assignment": 170, "runtime": 100, "metadata": 180, "fingerprint": 110}
        for column in columns:
            tree.heading(column, text=labels[column])
            tree.column(column, width=widths[column], anchor="w")
        connections = result.data.get("connections", []) if isinstance(result.data, Mapping) else []
        for item in connections:
            item = self._mapping(item)
            tree.insert("", "end", values=(
                item.get("connection_id", ""), item.get("provider", ""), item.get("model", ""),
                ", ".join(item.get("assignments", [])) if isinstance(item.get("assignments"), list) else "",
                item.get("runtime_status", "UNOBSERVED"), item.get("metadata_status", "UNKNOWN"),
                "present" if item.get("fingerprint_present") else "absent",
            ))
        tree.grid(row=0, column=0, sticky="nsew")
        self.body.rowconfigure(0, weight=1)
        toolbar = self.ttk.Frame(self.body)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        for provider in ("openrouter", "groq"):
            self.ttk.Button(toolbar, text=f"Import {provider} source", command=lambda p=provider: self._import(p)).pack(side="left", padx=(0, 8))
        self._set_status(result, "Connection registry refreshed")

    def _import(self, provider: str) -> None:
        result = self.service.dispatch(ApplicationIntent("import_provider_connections", {"provider": provider}))
        self._set_status(result, f"Imported {provider} metadata without returning secrets")
        self.show("Connections & Pools")

    def _workers(self) -> None:
        self._header("Workers / Fleet", "Router-owned health, leases, and availability; the UI adds no worker authority.")
        result = self.service.dispatch(ApplicationIntent("refresh_dashboard", {}))
        workers = self._mapping(result.data.get("workers"))
        cards = self.ttk.Frame(self.body)
        cards.grid(row=0, column=0, sticky="ew")
        healthy = workers.get("healthy", []) if isinstance(workers.get("healthy"), list) else []
        failed = workers.get("failed", []) if isinstance(workers.get("failed"), list) else []
        leased = workers.get("leases", {}) if isinstance(workers.get("leases"), Mapping) else {}
        for index, item in enumerate((
            ("Healthy", str(len(healthy)), "available"),
            ("Failed", str(len(failed)), "runtime/external"),
            ("Leased", str(len(leased)), "active task leases"),
        )):
            self._card(cards, index, item[0], item[1], item[2])
        self._set_status(result, "Worker fleet refreshed")
        table = self.ttk.LabelFrame(self.body, text="Active Leases", padding=10)
        table.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        self.body.rowconfigure(1, weight=1)
        lease_tree = self.ttk.Treeview(table, columns=("task", "worker", "role", "standby"), show="headings")
        for col, label in (("task", "Task"), ("worker", "Worker"), ("role", "Role"), ("standby", "Standby")):
            lease_tree.heading(col, text=label)
            lease_tree.column(col, width=180, anchor="w")
        for task_id, lease in leased.items():
            lease = self._mapping(lease)
            lease_tree.insert("", "end", values=(task_id, lease.get("worker_id"), lease.get("role"), lease.get("standby", False)))
        lease_tree.pack(fill="both", expand=True)

    def _run_plan(self) -> None:
        self._header("Run / Plan", "Execution remains exclusively owned by the canonical Core runtime.")
        form = self.ttk.LabelFrame(self.body, text="Canonical Run", padding=12)
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        self.ttk.Label(form, text="Task ID").grid(row=0, column=0, padx=(0, 8))
        task_id = self.tk.StringVar(value="UI-TASK-001")
        self.tk.Entry(form, textvariable=task_id, width=22).grid(row=0, column=1, sticky="w")
        output = self.ttk.LabelFrame(self.body, text="Run Evidence", padding=12)
        output.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        output.columnconfigure(0, weight=1)
        output.rowconfigure(0, weight=1)
        text = self.tk.Text(output, wrap="word", font=("Segoe UI", 10), relief="flat")
        text.grid(row=0, column=0, sticky="nsew")
        self.body.rowconfigure(1, weight=1)
        def run() -> None:
            result = self.service.dispatch(ApplicationIntent("run_task", {"task_id": task_id.get()}))
            text.delete("1.0", "end")
            text.insert("1.0", result.error or ("Canonical run completed.\n\n" + self._format_run(result.data)))
            self._set_status(result, "Canonical run completed")
        self.ttk.Button(form, text="Run Task", style="Primary.TButton", command=run).grid(row=0, column=2, padx=(10, 0))

        evidence = self.service.dispatch(ApplicationIntent("session_evidence", {}))
        last_run = self._mapping(evidence.data.get("last_run"))
        if last_run:
            text.insert("1.0", "Last run from this session:\n\n" + self._format_run(last_run))

    def _format_run(self, data: Mapping[str, Any]) -> str:
        lines = [
            f"Status: {data.get('status', 'UNKNOWN')}",
            f"Task: {data.get('task_id', '-')}",
        ]
        records = data.get("task_records", [])
        if isinstance(records, list):
            lines.append(f"Task records: {len(records)}")
            for record in records:
                record = self._mapping(record)
                product = self._mapping(record.get("work_product"))
                lines.append(f"  • {self._mapping(record.get('task')).get('task_id', '?')} — {product.get('status', 'UNKNOWN')}")
        return "\n".join(lines)

    def _evidence(self) -> None:
        self._header("Evidence & Activity", "Structured application events, redacted before display.")
        result = self.service.dispatch(ApplicationIntent("session_evidence", {}))
        events = result.data.get("events", []) if isinstance(result.data, Mapping) else []
        columns = ("status", "intent", "summary")
        tree = self.ttk.Treeview(self.body, columns=columns, show="headings")
        for col, label, width in (("status", "Status", 110), ("intent", "Intent", 230), ("summary", "Evidence", 700)):
            tree.heading(col, text=label)
            tree.column(col, width=width, anchor="w")
        for event in events:
            event = self._mapping(event)
            status = str(event.get("status", "UNKNOWN"))
            data = self._mapping(event.get("data"))
            summary = json.dumps(data, ensure_ascii=False, default=str)[:300]
            tree.insert("", "end", values=(status, event.get("intent", ""), summary))
        tree.grid(row=0, column=0, sticky="nsew")
        self.body.rowconfigure(0, weight=1)
        self._set_status(result, "Evidence refreshed")

    def _git(self) -> None:
        self._header("Git & Changes", "Inspection-only application view. Mutation authority remains in the existing Git control plane.")
        result = self.service.dispatch(ApplicationIntent("git_snapshot", {}))
        data = self._mapping(result.data)
        frame = self.ttk.LabelFrame(self.body, text="Repository", padding=14)
        frame.grid(row=0, column=0, sticky="ew")
        self._status_lines(frame, [
            ("Branch", str(data.get("branch", "UNKNOWN"))),
            ("HEAD", str(data.get("head", "UNKNOWN"))),
            ("Worktree", "CLEAN" if data.get("clean") else "DIRTY"),
            ("Authority", str(data.get("authority", "UNKNOWN"))),
        ])
        self._set_status(result, "Git snapshot refreshed")

    def _tests(self) -> None:
        self._header("Tests & Verification", "The UI distinguishes evidence states and never invents results.")
        frame = self.ttk.Frame(self.body)
        frame.grid(row=0, column=0, sticky="nsew")
        self.body.rowconfigure(0, weight=1)
        checks = (
            ("Compile", "Reported by CI / Windows acceptance"),
            ("Focused tests", "Reported by current promotion run"),
            ("Full regression", "Reported by current promotion run"),
            ("Security audit", "Reported by current promotion run"),
            ("Provider smoke", "Local credential environment required"),
            ("Windows E2E", "Pending current UI promotion gate"),
        )
        for row, (name, detail) in enumerate(checks):
            self.ttk.Label(frame, text=name, style="CardValue.TLabel").grid(row=row, column=0, sticky="w", padx=8, pady=9)
            self.ttk.Label(frame, text=detail, style="Subtitle.TLabel").grid(row=row, column=1, sticky="w", padx=8, pady=9)
        self._set_status(ApplicationResult("NOT_RUN", {}), "Evidence is read-only on this surface")

    def _safety(self) -> None:
        self._header("Safety & Policy", "The Control Center explains policy; it cannot override it.")
        frame = self.ttk.LabelFrame(self.body, text="Core Safety Invariants", padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        self.body.rowconfigure(0, weight=1)
        for row, (state, detail) in enumerate((
            ("UNKNOWN / CONFLICT", "SAFE_STOP; autonomous execution is blocked"),
            ("Model output", "Untrusted input; validated before authority is granted"),
            ("Mutation", "Independent validation + authorization + checkpoint required"),
            ("Git terminal", "Inspection-only; mutation uses the dedicated control plane"),
            ("Secrets", "Redacted before UI activity/evidence and never rendered after import"),
        )):
            self.ttk.Label(frame, text=state, style="CardValue.TLabel").grid(row=row, column=0, sticky="w", padx=8, pady=7)
            self.ttk.Label(frame, text=detail, style="Subtitle.TLabel", wraplength=720).grid(row=row, column=1, sticky="w", padx=8, pady=7)

    def _settings(self) -> None:
        self._header("Settings / Diagnostics", "Non-secret application and runtime information.")
        frame = self.ttk.LabelFrame(self.body, text="Environment", padding=16)
        frame.grid(row=0, column=0, sticky="ew")
        self._status_lines(frame, [
            ("Application", "AI-Agent Control Center"),
            ("Python", sys.version.split()[0]),
            ("Platform", sys.platform),
            ("Workspace", str(self.service.workspace_root or "none")),
            ("Credentials rendered", "NO"),
            ("Application authority", "typed intents over Core"),
        ])

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    ControlCenterApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
