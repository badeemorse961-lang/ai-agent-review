# Professional Desktop Control Center

## Entry point

`control_center.pyw` is the documented Windows user-facing entry point. It launches the Tk/ttk Control Center without a developer console. `desktop_control_center.py` remains the Python module entry point for diagnostics and development.

## Boundary

```text
Control Center
    ↓ ApplicationIntent
ControlCenterService
    ↓
Existing Core read models / CentralLeader / routing / project understanding
    ↓
Canonical orchestration and existing execution authorities
```

The UI owns presentation and structured operator intent only. It does not implement routing, validation, authorization, mutation, or shell execution. Git inspection is routed through the existing `TerminalExecutor` + `GitSafetyPolicy` path.

## Current capabilities

- Dashboard reads project understanding, router state, Git inspection, and the last structured plan.
- Leader Chat submits a typed goal/task intent to `CentralLeader`; malformed, unavailable, or unauthorized runtime dependencies surface as bounded status rather than simulated output.
- Projects selects a bounded workspace and re-runs the real understanding pipeline.
- Connections & Pools reads authoritative registry assignments and non-secret connection metadata and can import protected local provider secret sources without returning raw key material.
- Workers displays router-owned runtime state.
- Run / Plan and Evidence & Activity expose actual session data captured by the application boundary.
- Git & Changes uses the existing inspection-only terminal policy.
- Tests & Verification, Safety & Policy, and Settings/Diagnostics explicitly distinguish available evidence from results the GUI cannot legitimately invent.

## Explicit limitations

The Control Center is an actual Windows application boundary, but full product acceptance remains blocked until a production WorkerAdapter emits the authoritative `WorkerWorkProduct` contract and a Windows E2E run proves the complete UI acceptance matrix in `PRODUCT_UI_SPEC.md`.

Dynamic Connection Onboarding remains outside this milestone and is still configuration-driven only.
