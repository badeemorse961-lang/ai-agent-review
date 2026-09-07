# AI-Agent Professional Desktop UI Specification

## 1. Purpose

The AI-Agent is a desktop product, not a PowerShell-first tool. PowerShell, Python entry points, and other command-line interfaces remain development, diagnostics, and advanced-operator interfaces; they are not the primary end-user operating surface.

The primary product surface must be a professional Windows desktop **Control Center** that exposes the existing autonomous-engineering core without bypassing its authority boundaries.

The UI is an application boundary over the Core. It must not duplicate orchestration logic, weaken policy checks, expose raw credentials, or create a second execution authority.

## 2. Product Principle

```text
Professional Desktop UI
        ↓
Application / UI Service Boundary
        ↓
AI-Agent Core
        ↓
Leader / Workers / Validation / Authorization
        ↓
Execution Gate / Sandbox / Git Mutation Control Plane
```

The UI presents state, captures operator intent, starts authorized workflows, and renders evidence. The Core remains the sole authority for planning, validation, execution authorization, mutation, and safety stops.

## 3. Primary UI Goals

The application must make the system operationally understandable without requiring the user to read terminal output or internal Python structures.

The UI must provide:

1. project selection and active-project status;
2. natural-language communication with the Central Leader;
3. visible autonomous-run lifecycle and current phase;
4. live project health and state classification;
5. worker/leader/provider connection management;
6. secure addition, rotation, disablement, and health checking of provider credentials without displaying raw secrets after submission;
7. model/provider/role/pool visibility based on registry configuration and runtime health;
8. work-plan and task/dependency visibility;
9. activity, execution, validation, and safety-stop evidence;
10. Git/worktree and mutation-control status;
11. test/build/smoke/security results;
12. approvals and exceptional high-risk actions only where policy requires them;
13. safe stop, pause/cancel, and recovery actions where supported by the Core;
14. settings, policy visibility, diagnostics, and version/build information.

## 4. Main Screens

### 4.1 Dashboard

The home screen must provide an immediate operational summary:

- active project and workspace path;
- project state: BUILD / CONTINUE / MAINTAIN / REPAIR / CONFLICT / UNKNOWN;
- current run status: idle / analyzing / planning / executing / validating / verifying / blocked / completed / failed;
- current leader connection/provider/model and failover status without revealing credentials;
- worker pool availability by role;
- current task/phase and progress;
- latest validation verdict;
- latest test/build results;
- Git state and mutation-control readiness;
- active warnings, safety stops, and unresolved issues;
- last successful run and recent run history.

The dashboard must favor actionable status cards and drill-down evidence over decorative telemetry.

### 4.2 Chat with Central Leader

The primary interaction model is a persistent written conversation with the Central Leader.

The user must be able to:

- enter a goal or change request in natural language;
- see the leader's interpreted objective and resulting plan;
- see clarifying questions when evidence is insufficient;
- inspect requested files/resources before granting explicitly bounded access;
- observe plan/task progress;
- receive concise status updates and completion reports;
- inspect evidence attached to important claims;
- start a new project task or continue an existing task from the same workspace.

The chat UI must distinguish clearly between:

- user intent;
- leader reasoning/plan;
- worker output/work product;
- independent validation;
- execution authorization;
- verified result.

No chat message may directly execute a shell command or mutate files outside the Core control path.

### 4.3 Projects

Provide a project/workspace manager showing:

- known projects;
- active project;
- workspace root;
- project classification;
- repository identity and branch information;
- recent runs;
- project health;
- detected documentation/specification sources;
- last scan/discovery time;
- unresolved gaps, conflicts, or repair findings.

Adding a project must use a bounded workspace/resource declaration model rather than granting arbitrary filesystem access.

### 4.4 Connections & Pools

Provide a secure management screen for provider connections.

Required capabilities:

- add a Groq/OpenRouter connection;
- import connection credentials from the supported local secret-source workflow;
- assign or review role/domain membership through the authoritative registry/configuration path;
- enable/disable a connection where supported;
- rotate a credential without exposing the previous value;
- run a health check;
- view provider/model/connection ID, runtime state, last health result, and failure classification;
- inspect pool membership and available capacity;
- distinguish configured, healthy, unhealthy, exhausted, disabled, and not-present states;
- detect duplicate/fingerprint matches safely;
- never display raw key material after entry/import;
- never write secrets into logs, chat transcripts, screenshots, diagnostics, or persistent runtime state.

Connection IDs remain identifiers and must not impose a fixed maximum capacity.

The UI may provide a guided auto-assignment workflow in the future, but any automatic role assignment must be performed by the Core/configuration authority and must be explainable and reversible. The UI itself must not invent routing policy.

### 4.5 Run / Plan View

For each autonomous task, provide a timeline or graph of the canonical flow:

```text
Discovery
  → Analysis
  → Gap/Compliance
  → Leader Plan
  → Decomposition
  → Worker Execution
  → Independent Validation
  → Execution Authorization
  → Execution Gate
  → Tests
  → Verification
  → APPROVE / SAFE_STOP / ROLLBACK→VERIFY
```

Each step must expose status, duration where available, owning component, and evidence summary.

Tasks should show dependencies, current owner, retry/recovery state, and whether they are read-only or mutation-capable.

### 4.6 Workers

Provide a fleet view with:

- role;
- connection ID;
- provider/model;
- health/lease state;
- busy/idle/standby state;
- current task;
- recent result;
- validation status;
- failure count/reason when safe to disclose;
- last seen/health-check timestamp.

The UI must not imply that a worker has authority beyond its role and the Core's execution boundaries.

### 4.7 Evidence & Activity

Provide a searchable activity/evidence stream covering:

- project scans;
- classifications;
- plan decisions;
- worker work products;
- validation verdicts;
- authorization decisions;
- checkpoints;
- execution results;
- test/build results;
- Git mutation evidence;
- safety stops;
- provider failures and failover events.

Sensitive values must be redacted before reaching this view.

### 4.8 Git & Changes

Provide an inspection-first Git screen showing:

- current branch and HEAD;
- clean/dirty state;
- changed files;
- validated task target set;
- staged target set when mutation is in progress;
- latest commit evidence;
- mutation authorization/checkpoint state;
- exact committed target-set verification;
- failure evidence and required recovery state.

The UI must not expose unrestricted Git operations. Remote mutation and history-rewriting commands remain unavailable through the application.

### 4.9 Tests & Verification

Provide a verification screen showing:

- syntax/compile status;
- targeted tests;
- full regression suite;
- smoke/integration tests;
- security audit;
- Windows acceptance evidence;
- latest pass/fail timestamps;
- run identifiers and relevant artifacts/log references;
- whether the evidence is current enough to support promotion.

### 4.10 Safety & Policy Center

Provide a clear policy view for:

- current safety state;
- UNKNOWN / CONFLICT stops;
- active execution blocks;
- resource authorization;
- process sandbox mode;
- secret-redaction state;
- mutation lock state;
- high-risk action requirements;
- why an operation was rejected or stopped.

Safety explanations must be understandable to an operator while preserving sensitive implementation details.

### 4.11 Settings / Diagnostics

Provide non-secret configuration and diagnostics such as:

- UI/core version;
- registry revision/hash where available;
- runtime environment summary;
- log/evidence retention policy;
- default project behavior;
- appearance/accessibility preferences;
- diagnostics export that is redacted and safe by construction.

Credentials must be managed through the dedicated connection workflow, not general settings text boxes.

## 5. UX and Visual Quality

The Control Center must look and behave like a professional modern Windows application, not a developer console wrapped in a window.

Required qualities:

- consistent information hierarchy;
- responsive desktop layout;
- sidebar/navigation with clear active state;
- restrained professional visual language;
- light and dark themes;
- clear success/warning/error/safe-stop states;
- accessible typography and keyboard navigation;
- confirmation only for exceptional/high-risk actions, not normal autonomous steps;
- non-blocking progress indicators;
- empty states and actionable error states;
- searchable tables/views for connections, tasks, evidence, and projects;
- detailed views available without overwhelming the dashboard;
- explicit timestamps and run/task identifiers for operational traceability.

Visual polish is a product requirement, but it must never come at the expense of evidence clarity or safety transparency.

## 6. Security Requirements for the UI

1. Raw provider keys must never be rendered after submission/import.
2. Keys must never appear in chat transcripts, notifications, telemetry, screenshots generated by the app, or diagnostic exports.
3. The UI cannot bypass Core authorization, validation, sandbox, or mutation policy.
4. UI-triggered actions must be represented as structured application intents, not arbitrary shell strings.
5. User-entered text is untrusted input and must be validated before it reaches the Core.
6. Project paths are subject to the same bounded resource authorization as non-UI execution.
7. Safety-stop state must be fail-closed and visible.
8. Destructive or high-risk actions must use policy-defined confirmation gates.
9. Diagnostics must pass through the centralized redaction boundary before export or persistence.

## 7. Functional Acceptance Criteria

The desktop product is not considered UI-complete until a Windows acceptance run proves at least:

- launch from the documented user-facing entry point without requiring PowerShell for normal operation;
- create/select a project and display its current state;
- send a written goal to the Central Leader and display the resulting structured plan;
- display live leader/worker connection health and role/pool membership;
- add or import a provider connection without exposing the secret afterward;
- show task execution through the canonical orchestration chain;
- show independent validation and authorization states;
- show test/build/verification evidence;
- show Git inspection and mutation evidence without exposing unrestricted Git controls;
- demonstrate a representative SAFE_STOP and explain the reason;
- preserve redaction across UI-visible logs, errors, activity, and diagnostics;
- recover cleanly from an unavailable provider/connection according to runtime failover rules;
- remain usable when a project is idle, actively running, blocked, failed, or completed.

## 8. Non-Goals

The UI must not:

- reimplement the leader/worker routing algorithm;
- become a second source of truth for registry or policy;
- store raw credentials in project files;
- expose unrestricted terminal, Git, filesystem, or remote-network authority;
- require manual confirmation for ordinary autonomous development steps;
- promise OS-level isolation that the underlying runtime does not actually provide.

## 9. Implementation Direction

Preferred implementation strategy:

- keep the current Python Core unchanged at its authority boundaries;
- introduce a thin application/service layer for UI commands and read models;
- implement the desktop shell as a native-feeling Windows application;
- keep UI state derived from authoritative Core/runtime state;
- use typed request/response contracts rather than shell-command interpolation;
- add deterministic adapter tests plus Windows end-to-end acceptance tests;
- keep the UI independently testable from the Core.

The implementation technology may be selected by engineering based on repository constraints, but the final product must satisfy the behavior and UX requirements above.

## 10. Completion Gate

The GUI milestone closes only when implementation, integration, security, regression, and real Windows acceptance evidence all pass.

A visually attractive mockup, static dashboard, or launcher alone is not sufficient evidence.
