from __future__ import annotations

import sys
from typing import Any, Mapping

from application_boundary import ApplicationIntent, ApplicationResult, ControlCenterService


class ControlCenterApp:
    """Windows desktop Control Center; presentation only, Core remains authoritative."""

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
        self.root.geometry("1360x860")
        self.root.minsize(1100, 720)
        self._configure_style()
        self._build_shell()
        self.show("Dashboard")

    def _configure_style(self) -> None:
        style = self.ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 21, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
        style.configure("Nav.TButton", anchor="w", padding=(14, 10))
        style.configure("Card.TLabelframe", padding=10)
        style.configure("Treeview", rowheight=26, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

    def _build_shell(self) -> None:
        ttk = self.ttk
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(self.root, padding=12)
        sidebar.grid(row=0, column=0, sticky="ns")
        ttk.Label(sidebar, text="AI-Agent", style="Title.TLabel").pack(anchor="w", pady=(4, 18))
        for name in (
            "Dashboard", "Chat", "Projects", "Connections & Pools", "Workers", "Run / Plan",
            "Evidence & Activity", "Git & Changes", "Tests & Verification", "Safety & Policy",
            "Settings / Diagnostics",
        ):
            ttk.Button(sidebar, text=name, style="Nav.TButton", command=lambda n=name: self.show(n)).pack(fill="x", pady=2)
        ttk.Separator(sidebar).pack(fill="x", pady=12)
        ttk.Button(sidebar, text="Exit", command=self.root.destroy).pack(fill="x")

        main = ttk.Frame(self.root, padding=(18, 14))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        self.header = ttk.Frame(main)
        self.header.grid(row=0, column=0, sticky="ew")
        self.body = ttk.Frame(main)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.status = ttk.Label(main, text="Ready", style="Subtitle.TLabel")
        self.status.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _header(self, title: str, subtitle: str) -> None:
        for child in self.header.winfo_children():
            child.destroy()
        self.ttk.Label(self.header, text=title, style="Title.TLabel").pack(anchor="w")
        self.ttk.Label(self.header, text=subtitle, style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))

    def _clear(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()

    def _output(self, text: str) -> None:
        widget = self.tk.Text(self.body, wrap="word", font=("Consolas", 10), relief="flat")
        widget.insert("1.0", text)
        widget.configure(state="disabled")
        widget.grid(row=0, column=0, sticky="nsew")

    def _json(self, data: Mapping[str, Any]) -> str:
        import json
        return json.dumps(data, indent=2, ensure_ascii=False, default=str)

    def show(self, page: str) -> None:
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
        self._header("Dashboard", "Current project and runtime state from authoritative Core read models.")
        result = self.service.dispatch(ApplicationIntent("refresh_dashboard", {}))
        self.status.configure(text=result.error or "Dashboard refreshed")
        self._output(self._json(result.data) if not result.error else f"{result.status}: {result.error}")

    def _chat(self) -> None:
        self._header("Chat with Central Leader", "Natural-language goals are structured intents; they are never shell commands.")
        self.body.rowconfigure(1, weight=1)
        form = self.ttk.Frame(self.body)
        form.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        form.columnconfigure(1, weight=1)
        self.ttk.Label(form, text="Goal").grid(row=0, column=0, padx=(0, 8))
        goal = self.tk.StringVar()
        self.tk.Entry(form, textvariable=goal).grid(row=0, column=1, sticky="ew")
        self.ttk.Label(form, text="Task ID").grid(row=0, column=2, padx=(8, 4))
        task_id = self.tk.StringVar(value="UI-TASK-001")
        self.tk.Entry(form, textvariable=task_id, width=18).grid(row=0, column=3)
        output = self.tk.Text(self.body, wrap="word", font=("Consolas", 10))
        output.grid(row=1, column=0, sticky="nsew")

        def send() -> None:
            result = self.service.dispatch(ApplicationIntent("send_leader_goal", {"goal": goal.get(), "task_id": task_id.get()}))
            output.delete("1.0", "end")
            output.insert("1.0", self._json(result.data) if not result.error else f"{result.status}: {result.error}")
            self.status.configure(text=result.error or result.status)

        self.ttk.Button(form, text="Send", command=send).grid(row=0, column=4, padx=(8, 0))

    def _projects(self) -> None:
        self._header("Projects", "Bounded workspace selection using the existing project understanding pipeline.")
        row = self.ttk.Frame(self.body)
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(1, weight=1)
        self.ttk.Label(row, text="Workspace").grid(row=0, column=0, padx=(0, 8))
        value = self.tk.StringVar(value=str(self.service.workspace_root or ""))
        self.tk.Entry(row, textvariable=value).grid(row=0, column=1, sticky="ew")
        def select() -> None:
            from tkinter import filedialog
            path = filedialog.askdirectory(title="Select project workspace")
            if path:
                result = self.service.dispatch(ApplicationIntent("select_project", {"workspace_root": path}))
                self.status.configure(text=result.error or "Project selected")
                self.show("Dashboard")
        self.ttk.Button(row, text="Select", command=select).grid(row=0, column=2, padx=8)
        self._output("Project state is derived from ProjectUnderstandingPipeline. Selecting a path does not grant arbitrary filesystem authority.")

    def _connections(self) -> None:
        self._header("Connections & Pools", "Assignments come from config/registry.json; runtime state is observational.")
        result = self.service.dispatch(ApplicationIntent("refresh_connections", {}))
        columns = ("id", "provider", "model", "assignment", "metadata", "fingerprint")
        tree = self.ttk.Treeview(self.body, columns=columns, show="headings")
        labels = {"id": "Connection ID", "provider": "Provider", "model": "Model", "assignment": "Assignment", "metadata": "Metadata", "fingerprint": "Fingerprint"}
        for column in columns:
            tree.heading(column, text=labels[column])
            tree.column(column, width=150, anchor="w")
        connections = result.data.get("connections", []) if isinstance(result.data, Mapping) else []
        for item in connections:
            tree.insert("", "end", values=(
                item.get("connection_id"), item.get("provider"), item.get("model"),
                ", ".join(item.get("assignments", [])), item.get("metadata_status"),
                "present" if item.get("fingerprint_present") else "absent",
            ))
        tree.grid(row=0, column=0, sticky="nsew")
        self.body.rowconfigure(0, weight=1)
        bar = self.ttk.Frame(self.body)
        bar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for provider in ("openrouter", "groq"):
            self.ttk.Button(bar, text=f"Import {provider} secret source", command=lambda p=provider: self._import(p)).pack(side="left", padx=(0, 8))
        self.status.configure(text=result.error or "Connection registry refreshed")

    def _import(self, provider: str) -> None:
        result = self.service.dispatch(ApplicationIntent("import_provider_connections", {"provider": provider}))
        self.status.configure(text=result.error or f"Imported {provider} metadata without returning secrets")
        self.show("Connections & Pools")

    def _workers(self) -> None:
        self._header("Workers / Fleet", "Worker health and leases remain runtime observations owned by WorkerRouter.")
        result = self.service.dispatch(ApplicationIntent("refresh_dashboard", {}))
        workers = result.data.get("workers", {}) if isinstance(result.data, Mapping) else {}
        self._output(self._json(workers))

    def _run_plan(self) -> None:
        self._header("Run / Plan", "The displayed plan is the real leader response captured by the application service.")
        evidence = self.service.dispatch(ApplicationIntent("session_evidence", {}))
        plan = evidence.data.get("last_plan") if isinstance(evidence.data, Mapping) else None
        self._output(self._json(plan) if isinstance(plan, Mapping) else "No leader plan has been captured in this application session.")

    def _evidence(self) -> None:
        self._header("Evidence & Activity", "Application events are structured and pass through centralized redaction before display.")
        result = self.service.dispatch(ApplicationIntent("session_evidence", {}))
        self._output(self._json(result.data))

    def _git(self) -> None:
        self._header("Git & Changes", "Inspection-only view through the existing TerminalExecutor/GitSafetyPolicy path.")
        result = self.service.dispatch(ApplicationIntent("git_snapshot", {}))
        self._output(self._json(result.data) if not result.error else f"{result.status}: {result.error}")

    def _tests(self) -> None:
        self._header("Tests & Verification", "Evidence is displayed from authoritative execution sources; the GUI does not invent results.")
        self._output("PASS / FAIL / NOT RUN / STALE / UNKNOWN remain distinct evidence states.\n\nThe application surface does not execute arbitrary test commands itself.")

    def _safety(self) -> None:
        self._header("Safety & Policy", "The UI explains Core policy; it never becomes a parallel policy authority.")
        self._output("UNKNOWN / CONFLICT → SAFE_STOP\nMutation → validation + authorization + checkpoint\nGit terminal → inspection only\nRaw secrets → never rendered after input/import")

    def _settings(self) -> None:
        self._header("Settings / Diagnostics", "Non-secret runtime information only.")
        self._output(
            f"Application: AI-Agent Control Center\nPython: {sys.version.split()[0]}\n"
            f"Platform: {sys.platform}\nWorkspace: {self.service.workspace_root or 'none'}\n"
            "Credentials rendered: NO\nApplication authority: typed intents over Core"
        )

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    ControlCenterApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
