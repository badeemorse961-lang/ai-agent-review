# AI-Agent Internal Model Benchmark

## Status

**BENCHMARK GATE: NOT YET DECIDED**

This benchmark stage is a prerequisite for changing any production model, leader pool, worker pool, or account distribution. The current production registry is intentionally untouched by this stage.

The benchmark runner uses the existing protected secret-store abstraction, sends the same task-scoped repository context to each candidate, and evaluates outputs without writing raw credentials or benchmark outputs to Git. Code proposals are applied only to disposable benchmark workspaces.

## A. Candidate models

### OpenRouter shortlist

1. `openai/gpt-5.6-luna`
   - 1M-class context; tool calling; structured outputs with JSON Schema.
   - Current listed price: $0.20/M input and $1.20/M output.
   - Included because the project needs long-context planning, tool use, structured decisions, and production reliability.

2. `z-ai/glm-5.3`
   - 1M-class context; reasoning; tool calling; JSON response support.
   - Current listed price: $1.12/M input and $3.52/M output.
   - Included as a high-end software-engineering and long-horizon agent candidate.

3. `z-ai/glm-5.3-flash:free`
   - 1M-class context; coding and long-horizon agent orientation.
   - Free endpoint; rate limits apply.
   - Included as a low-cost/high-throughput candidate that still targets coding and agentic work.

4. `nvidia/nemotron-3-ultra-550b-a55b:free`
   - 1M-class context; reasoning/orchestration; tool calling.
   - Free endpoint; current OpenRouter documentation says structured `response_format` is not available on the free endpoint.
   - Included because it is already present in the project's current Leader baseline and is directly relevant to orchestration.

5. `minimax/minimax-m3:free`
   - 1M-class context; long-horizon agentic work, coding, and tool use.
   - Free endpoint; supports tool calling and response-format JSON, but not strict JSON-schema enforcement on the referenced endpoint.
   - Included to test whether free long-context agentic capability is sufficient without paying for frontier routing.

`openrouter/free` is not a production candidate. It is useful for exploration only because its selected model can change between requests.

### Groq shortlist

1. `openai/gpt-oss-120b`
   - Current Groq production model; 131,072-token context.
   - Tool use, browser search, code execution, reasoning, JSON Schema structured outputs.
   - Current listed price: $0.15/M input and $0.60/M output.

2. `openai/gpt-oss-20b`
   - 131,072-token context.
   - Current Groq documentation lists strict JSON Schema support and a materially higher token rate than 120B.
   - Included to determine whether a smaller Groq model can own SIMPLE work without consuming premium worker capacity.

No candidate is promoted by catalog metadata alone.

## B. Benchmark corpus

The reproducible corpus is `model_benchmark_corpus.json`.

The current suite contains project-specific tasks spanning:

- SIMPLE: bounded tests, small parsing edge cases, documentation/validation decisions.
- MEDIUM: multi-file lifecycle repairs, cross-module read-model behavior, provider-failure analysis.
- COMPLEX: routing failover, WorkerWorkProduct integrity, architecture recovery, security-sensitive orchestration.
- LEADER: project understanding, requirement interpretation, authorization-aware planning, dependency/risk analysis, and recovery planning.

The exact repository context is task-scoped. Each candidate sees the same context files and the same prompt for the same task.

## C. Scoring matrix

Initial weighting, subject to benchmark evidence:

| Dimension | Weight |
|---|---:|
| Correctness | 30% |
| Solution / code quality | 15% |
| Reasoning quality | 15% |
| Instruction adherence | 10% |
| Tool / structured-output correctness | 10% |
| Regression safety | 10% |
| Latency | 5% |
| Reliability | 5% |
| **Total** | **100%** |

Correctness and safety are hard gates. A low-cost model cannot win by latency or price if it violates invariants, produces invalid work products, causes regressions, or breaks instruction/authority boundaries.

## D. Leader decision gate

A model can become `LEADER_MODEL_PRIMARY` only after it demonstrates the strongest combined result on the LEADER corpus, with no unresolved safety/authority failures.

The leader benchmark emphasizes:

- project understanding;
- evidence-driven gap analysis;
- architecture reasoning;
- decomposition;
- dependency analysis;
- risk identification;
- recovery planning;
- authorization-aware sequencing;
- stable structured output.

`LEADER_MODEL_FAILOVER` must be selected independently rather than simply using the second-largest catalog popularity.

## E. Complex Worker decision gate

A model can become `COMPLEX_WORKER_MODEL_PRIMARY` only after it demonstrates reliable performance on COMPLEX coding, debugging, multi-file reasoning, recovery, and WorkerWorkProduct-compatible outputs.

`COMPLEX_WORKER_MODEL_FAILOVER` must be separately validated for the same failure modes.

## F. Groq capability boundary

The benchmark does not assume that provider identity implies task complexity.

The proposed policy boundary is:

```text
Required Capability
        ↓
Risk / Complexity Classification
        ↓
Eligible Capability Pool
        ↓
Healthy Connections
        ↓
Policy / Capacity Guard
        ↓
Worker Selection
```

Initial policy candidate for measurement:

- SIMPLE → Groq eligible by default.
- MEDIUM → Groq eligible only after passing the measured medium-task quality/reliability threshold and only when the task has no critical risk flag.
- COMPLEX → OpenRouter Complex Worker by default.
- CRITICAL → strongest approved worker path + independent validation.

A worker/model is never allowed to classify a task for itself.

## G. Simple / Medium / Complex rules

### SIMPLE

Use SIMPLE when all of the following are true:

- one bounded file/module or a trivial test/documentation surface;
- no routing, authorization, concurrency, security-sensitive, or lifecycle recovery change;
- one primary invariant or a small deterministic behavior change;
- focused verification is cheap and deterministic.

### MEDIUM

Use MEDIUM when one or more of the following applies while avoiding COMPLEX conditions:

- 2–4 modules or one interface boundary;
- bounded lifecycle/state change;
- small refactor with integration impact;
- debugging that requires evidence from multiple components;
- more than one dependency but a short, bounded recovery path.

### COMPLEX

Use COMPLEX when any of the following is true:

- 5+ modules or a long dependency chain;
- routing, failover, concurrency, recovery, architecture, security, or authorization is involved;
- exact WorkerWorkProduct binding/integrity is required;
- the task needs sustained multi-step agentic reasoning or large project context;
- failure can invalidate a major system control boundary.

A `CRITICAL` flag is a risk modifier over COMPLEX, not a fourth routing class. CRITICAL tasks require the strongest approved worker and independent validation.

## H. Account distribution simulation

Production allocation is deliberately **UNDECIDED** at this stage.

The benchmark runner/report must compare these OpenRouter Leader/advanced-worker splits:

- 20 / 80
- 30 / 70
- 40 / 60
- 50 / 50

The simulated comparison must use measured task mix, success rate, latency, failure/recovery behavior, and quota/capacity observations. A ratio is not considered evidence merely because it is a common industry heuristic.

Groq remains 100% worker-side during the benchmark; no Groq account is promoted to Leader by this stage.

## I. Proposed pool shape — not production-committed

The benchmark evaluates the following logical pools only:

```text
LEADER_PRIMARY
LEADER_FAILOVER
WORKER_SIMPLE
WORKER_MEDIUM
WORKER_COMPLEX
WORKER_FAILOVER
```

This document does **not** edit `config/registry.json` and does not introduce Dynamic Connection Auto-Assignment.

## J. Failure / recovery requirements

The benchmark must preserve these conclusions:

- complete Leader failure → fail-closed / SAFE_STOP;
- stable-ID credential replacement → identity and authoritative assignment stay unchanged;
- validation succeeds → recovered connection can re-enter the eligible set;
- Complex Worker pool failure → approved failover worker path remains available;
- no recovery path may bypass Core authorization or mutate routing authority implicitly.

## K. WorkerWorkProduct compatibility

A worker candidate is production-eligible only if it can participate in the authoritative `WorkerWorkProduct` path described in `WORKER_WORK_PRODUCT_PROTOCOL.md`.

A model that writes good code but cannot reliably produce the required bound work-product evidence is not accepted for the production worker role.

## L. Security findings / controls

Benchmark controls:

- provider credentials are resolved through `WindowsProtectedSecretStore` only;
- raw credentials are never included in prompts, reports, screenshots, metadata, or logs;
- code changes are evaluated only in a disposable benchmark workspace;
- verification commands are benchmark-authored, not model-authored;
- the production working tree and `config/registry.json` are not modified;
- benchmark output is local-only and must not be committed when it contains model responses or sensitive project context.

## M. Exact evidence and commands

### Preparation / validation

```text
python -m pytest -q test_model_benchmark.py
python -m compileall -q model_benchmark.py
```

### Example benchmark execution on Windows

Use existing connection IDs from the protected store; do not create or print raw API keys.

```text
python model_benchmark.py --repo-root . --model openai/gpt-5.6-luna --connection-id OR-01 --provider openrouter --repeats 2
python model_benchmark.py --repo-root . --model z-ai/glm-5.3 --connection-id OR-02 --provider openrouter --repeats 2
python model_benchmark.py --repo-root . --model z-ai/glm-5.3-flash:free --connection-id OR-03 --provider openrouter --repeats 2
python model_benchmark.py --repo-root . --model nvidia/nemotron-3-ultra-550b-a55b:free --connection-id OR-04 --provider openrouter --repeats 2
python model_benchmark.py --repo-root . --model minimax/minimax-m3:free --connection-id OR-05 --provider openrouter --repeats 2
python model_benchmark.py --repo-root . --model openai/gpt-oss-120b --connection-id GROQ-01 --provider groq --repeats 2
python model_benchmark.py --repo-root . --model openai/gpt-oss-20b --connection-id GROQ-02 --provider groq --repeats 2
```

These are benchmark invocations only. They do not edit the production registry, change pool membership, or perform automatic assignment.

### Important execution state

The assistant environment used to prepare this stage does not have access to the user's Windows DPAPI-protected credential store. Therefore live provider inference, latency, token, cost, and correctness measurements must be executed on the user's Windows environment using the protected store already configured for the project. No model winner is claimed before those measurements exist.

## Completion gate

Do not set a production model or pool allocation from this document alone. Required evidence before promotion:

1. full candidate benchmark results;
2. repeatability / reliability evidence;
3. regression-safe code-task validation;
4. tool and structured-output validation;
5. WorkerWorkProduct compatibility evidence;
6. Groq capability boundary based on measured thresholds;
7. allocation simulation using measured performance and observed workload/capacity;
8. clean security/redaction review;
9. only then, explicit production configuration change in a later step.

## External catalog references used only for candidate discovery

- OpenRouter model catalog and programming collection.
- OpenRouter current model pages for GPT-5.6 Luna, GLM 5.3, Nemotron 3 Ultra, MiniMax M3, and GLM 5.3 Flash.
- Groq current model documentation for GPT-OSS 120B/20B and Structured Outputs.
