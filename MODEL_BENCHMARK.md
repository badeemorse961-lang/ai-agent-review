# AI-Agent Internal Model Benchmark

## Status

**BENCHMARK HARNESS HARDENING IN PROGRESS — NO LIVE MATRIX AUTHORIZED**

This stage is evaluator-only. It cannot select or promote a Leader model, Complex Worker model, Groq capability boundary, or account allocation. Production routing, `config/registry.json`, allocation, and Dynamic Onboarding remain untouched.

## 1. Candidate scope

The benchmark retains the existing fixed candidate shortlist. `openrouter/free` is exploration-only and is not a production candidate because its selected model can vary between requests.

## 2. Corpus and semantic assertions

`model_benchmark_corpus.json` is version 2 and every benchmark task contains an `expected` assertion block.

Structured / Leader / tool assertions cover:

- expected classification;
- required decision fields and field types;
- required planning properties;
- required stop conditions;
- required evidence fields;
- dependency ordering;
- required safety constraints;
- forbidden outcomes and safety violations.

The evaluator produces `semantic_pass`. JSON key presence alone never establishes correctness.

Code / agentic implementation assertions cover:

- allowed target scope;
- required changed paths where applicable;
- expected file-level behavior markers;
- forbidden file changes/content where applicable;
- focused verification tests;
- WorkerWorkProduct envelope requirements for production-relevant code tasks.

## 3. Hard gates

The following are hard failures and cannot be masked by a high weighted score:

- secret leakage;
- forbidden production mutation;
- unauthorized approval / execution outcome;
- invalid WorkerWorkProduct contract;
- unsafe or unapproved tool usage;
- scope escape;
- forbidden path modification;
- invalid structured output where the task requires a structured contract;
- explicitly marked semantic safety/authority assertion failures.

Hard failures are recorded as codes in each run result.

## 4. Tool-calling benchmark

Tool task S4 runs a bounded two-turn loop:

```text
model → approved tool request → bounded local tool execution
      → tool result → model continuation → final structured result
```

The harness validates tool selection, argument shape, approved path scope, tool result handling, continuation structure, final semantic assertions, and absence of unsafe tools.

## 5. Reliability and repeatability

Reliability is measured from observed run outcomes rather than a placeholder value.

For each model/class the report includes:

- `success_rate`;
- `consistency_rate`;
- `hard_failure_rate`;
- `failure_variance`;
- aggregate reliability contribution.

Repeated execution is task-aware. A task is considered consistently successful only when all of its observed repeats pass the semantic and hard gates. A mixed sequence such as PASS / FAIL / PASS therefore remains inconsistent even when its arithmetic mean looks acceptable.

## 6. Required task-level output

For every model/class group the aggregate evidence includes:

- `tasks_total`;
- `tasks_passed`;
- `tasks_failed`;
- `pass_rate`;
- `hard_fail_count`;
- `mean_score`;
- `median_score`;
- `worst_task_score`;
- `mean_latency_ms`;
- `success_rate`;
- `consistency_rate`;
- `failure_variance`;
- `work_product_compatibility_rate`;
- input/output token totals and measured cost where available.

The runner emits evidence only. It does not emit a `BEST_LEADER`, `BEST_WORKER`, or promotion decision.

## 7. Leader and Complex Worker gates

A Leader candidate must satisfy the project-specific semantic gates for:

- project understanding;
- requirements/decomposition;
- authorization-aware planning;
- dependency and risk analysis;
- recovery reasoning;
- safety and fail-closed behavior.

A Complex Worker candidate must satisfy:

- code correctness;
- debugging / multi-file reasoning;
- regression safety;
- tool/structured-output behavior;
- WorkerWorkProduct compatibility;
- scope and authority invariants.

Popularity, external leaderboard position, or average score alone is insufficient for promotion.

## 8. Capability boundary evidence

After live inference, class-specific results must be comparable directly:

```text
Groq:
  SIMPLE = measured pass rate
  MEDIUM = measured pass rate
  COMPLEX = measured pass rate

OpenRouter candidate:
  SIMPLE = measured pass rate
  MEDIUM = measured pass rate
  COMPLEX = measured pass rate
```

The eventual MEDIUM eligibility threshold for Groq must be derived from those measured results and hard-gate behavior. The benchmark must not assume `provider == capability`.

The routing policy remains requirements-based:

```text
Task
 → Required Capability
 → Risk / Complexity Classification
 → Eligible Pool
 → Healthy Connections
 → Policy / Capacity Guard
 → Worker selection
```

`CRITICAL` is a risk modifier over COMPLEX and requires the strongest approved worker path plus independent validation.

## 9. Allocation evidence

The following Leader / advanced-worker ratios remain hypotheses only:

- 20 / 80
- 30 / 70
- 40 / 60
- 50 / 50

A production ratio may be selected only after measured workload mix, latency, success/reliability, failure/recovery behavior, availability, and quota/capacity observations are available.

No account or pool membership is changed by the benchmark harness.

## 10. Safety and workspace guarantees

Provider credentials are retrieved only through the existing protected secret-store abstraction. The benchmark does not read provider TXT files as a runtime credential fallback.

Code patches are evaluated only inside a temporary disposable workspace. The production working tree and `config/registry.json` are not modified by benchmark execution.

Benchmark result artifacts do not contain raw credentials. Model output is checked for secret-like material before it can be treated as a successful result.

## 11. Pre-live gate

Before any live candidate matrix is executed:

```text
python -m pytest -q test_model_benchmark.py
python -m compileall -q model_benchmark.py
python repository_security_audit.py
```

The benchmark-specific tests must cover semantic assertions, hard gates, tool-loop behavior, repeat consistency, and aggregation metrics. Repository security audit must pass. The disposable-workspace path must be exercised by focused tests.

Only after these conditions pass is the harness eligible for the status:

**BENCHMARK HARNESS READY FOR LIVE INFERENCE**

## 12. Post-live review gate

Live results remain evidence only until reviewed. The review must explicitly decide, or decline to decide:

- `LEADER_MODEL_PRIMARY` and `LEADER_MODEL_FAILOVER`;
- `COMPLEX_WORKER_MODEL_PRIMARY` and `COMPLEX_WORKER_MODEL_FAILOVER`;
- measured SIMPLE / MEDIUM / COMPLEX boundaries;
- Groq medium-task eligibility threshold;
- initial account allocation ratio.

A later production-configuration milestone is the only place where those decisions may change routing.

## 13. Current decision

**BENCHMARK GATE: NOT YET DECIDED**

No live model winner, capability boundary, or allocation ratio has been selected.
