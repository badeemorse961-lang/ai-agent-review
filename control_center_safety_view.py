from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from application_boundary import ApplicationIntent


_INSTALLED = "_real_safety_view_installed"


def install_real_safety_view(app_class: Any) -> None:
    """Install the evidence-backed Safety view without adding Core authority."""
    if getattr(app_class, _INSTALLED, False):
        return

    def _safety(self: Any) -> None:
        self._header(
            "Safety & Policy",
            "Core safety state is read-only here; the UI cannot override or clear a stop.",
        )

        evidence_result = self.service.dispatch(
            ApplicationIntent("session_evidence", {})
        )
        events = (
            evidence_result.data.get("events", [])
            if isinstance(evidence_result.data, Mapping)
            else []
        )
        safety_events: list[Mapping[str, Any]] = []
        for event in events:
            if not isinstance(event, Mapping):
                continue
            error = str(event.get("error") or "")
            status = str(event.get("status") or "")
            if (
                "SafetyStop" in error
                or "SAFE_STOP" in error
                or status in {"SAFE_STOP", "BLOCKED"}
            ):
                safety_events.append(event)

        frame = self.ttk.LabelFrame(
            self.body,
            text="Current Safety Evidence",
            padding=16,
        )
        frame.grid(row=0, column=0, sticky="nsew")
        self.body.rowconfigure(0, weight=1)

        if safety_events:
            event = safety_events[-1]
            error = str(event.get("error") or "Safety stop recorded by Core")
            data = event.get("data")
            state = (
                "SAFE_STOP"
                if "SafetyStop" in error or "SAFE_STOP" in error
                else str(event.get("status") or "BLOCKED")
            )
            summary = json.dumps(
                data,
                ensure_ascii=False,
                default=str,
                sort_keys=True,
            ) if data else "No additional event data"

            self.ttk.Label(
                frame,
                text=state,
                style="CardValue.TLabel",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=(4, 10))
            self.ttk.Label(
                frame,
                text="Reason",
                style="CardTitle.TLabel",
            ).grid(row=1, column=0, sticky="w", padx=8, pady=4)
            self.ttk.Label(
                frame,
                text=error,
                style="Subtitle.TLabel",
                wraplength=900,
                justify="left",
            ).grid(row=2, column=0, sticky="w", padx=8, pady=(0, 8))
            self.ttk.Label(
                frame,
                text="Affected task/run",
                style="CardTitle.TLabel",
            ).grid(row=3, column=0, sticky="w", padx=8, pady=4)
            self.ttk.Label(
                frame,
                text="Not available in the current safety event record",
                style="Subtitle.TLabel",
            ).grid(row=4, column=0, sticky="w", padx=8, pady=(0, 8))
            self.ttk.Label(
                frame,
                text="Event data",
                style="CardTitle.TLabel",
            ).grid(row=5, column=0, sticky="w", padx=8, pady=4)
            self.ttk.Label(
                frame,
                text=summary,
                style="Subtitle.TLabel",
                wraplength=900,
                justify="left",
            ).grid(row=6, column=0, sticky="w", padx=8, pady=(0, 10))
            self.ttk.Label(
                frame,
                text="Recovery",
                style="CardTitle.TLabel",
            ).grid(row=7, column=0, sticky="w", padx=8, pady=4)
            self.ttk.Label(
                frame,
                text="Resolve the Core evidence/authorization condition before retrying; no UI bypass is available.",
                style="Subtitle.TLabel",
                wraplength=900,
                justify="left",
            ).grid(row=8, column=0, sticky="w", padx=8, pady=(0, 14))
        else:
            self.ttk.Label(
                frame,
                text="No SAFE_STOP / BLOCKED event recorded in this session.",
                style="Subtitle.TLabel",
            ).grid(row=0, column=0, sticky="w", padx=8, pady=8)

        invariants = self.ttk.LabelFrame(
            self.body,
            text="Core Safety Invariants",
            padding=16,
        )
        invariants.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        for row, (state, detail) in enumerate(
            (
                ("UNKNOWN / CONFLICT", "SAFE_STOP; autonomous execution is blocked"),
                ("Model output", "Untrusted input; validated before authority is granted"),
                ("Mutation", "Independent validation + authorization + checkpoint required"),
                ("Git terminal", "Inspection-only; mutation uses the dedicated control plane"),
                ("Secrets", "Redacted before UI activity/evidence and never rendered after import"),
            )
        ):
            self.ttk.Label(
                invariants,
                text=state,
                style="CardValue.TLabel",
            ).grid(row=row, column=0, sticky="w", padx=8, pady=7)
            self.ttk.Label(
                invariants,
                text=detail,
                style="Subtitle.TLabel",
                wraplength=720,
            ).grid(row=row, column=1, sticky="w", padx=8, pady=7)

        self._set_status(evidence_result, "Safety evidence refreshed")

    app_class._safety = _safety
    setattr(app_class, _INSTALLED, True)
