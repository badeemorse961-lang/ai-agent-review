from __future__ import annotations

import argparse
import json
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import requests

from process_sandbox import ProcessSandbox
from protected_secret_store import SecretStore, WindowsProtectedSecretStore
from sandbox_policy import WorkspaceResourcePolicy
from terminal_executor import TerminalExecutor


BASE_DIR = Path(__file__).resolve().parent
CORPUS_FILE = BASE_DIR / "model_benchmark_corpus.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

OPENROUTER_CANDIDATES = (
    "openai/gpt-5.6-luna",
    "z-ai/glm-5.3",
    "z-ai/glm-5.3-flash:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "minimax/minimax-m3:free",
)
GROQ_CANDIDATES = (
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
)

OPENROUTER_IDS = {f"OR-{index:02d}" for index in range(1, 12)}
GROQ_IDS = {f"GROQ-{index:02d}" for index in range(1, 16)}

SCORE_WEIGHTS = {
    "correctness": 30,
    "solution_quality": 15,
    "reasoning": 15,
    "instruction_adherence": 10,
    "tool_structured": 10,
    "regression_safety": 10,
    "latency": 5,
    "reliability": 5,
}

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_context_file",
            "description": "Read a previously approved repository context file by path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_evidence",
            "description": "Record a bounded benchmark evidence label.",
            "parameters": {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["label"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str
    connection_id: str


@dataclass(frozen=True)
class RunResult:
    candidate: Candidate
    task_id: str
    task_class: str
    repeat: int
    ok: bool
    score: float
    dimensions: Mapping[str, float]
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    structured_ok: bool
    tool_ok: bool
    regression_ok: bool
    work_product_compatible: bool
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.candidate.provider,
            "model": self.candidate.model,
            "connection_id": self.candidate.connection_id,
            "task_id": self.task_id,
            "task_class": self.task_class,
            "repeat": self.repeat,
            "ok": self.ok,
            "score": self.score,
            "dimensions": dict(self.dimensions),
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "structured_ok": self.structured_ok,
            "tool_ok": self.tool_ok,
            "regression_ok": self.regression_ok,
            "work_product_compatible": self.work_product_compatible,
            "error": self.error,
        }


def load_corpus() -> dict[str, Any]:
    return json.loads(CORPUS_FILE.read_text(encoding="utf-8"))


def read_context(task: Mapping[str, Any], root: Path = BASE_DIR) -> str:
    chunks: list[str] = []
    for relative in task.get("context_files", []):
        path = root / str(relative)
        if not path.is_file():
            raise FileNotFoundError(f"Benchmark context file missing: {relative}")
        chunks.append(f"===== {relative} =====\n{path.read_text(encoding='utf-8')}\n===== END {relative} =====")
    return "\n\n".join(chunks)


def build_messages(task: Mapping[str, Any], context: str) -> list[dict[str, str]]:
    envelope = (
        "Return one JSON object and no markdown fences. For leader/structured tasks use "
        "classification, objective, plan, validation, risks, stop_conditions, evidence. "
        "For code tasks use summary, rationale, touched_paths, unified_diff. Never output secrets."
    )
    prompt = f"Task class: {task['class']}\nTask: {task['prompt']}\n\nRepository context:\n{context}"
    return [{"role": "system", "content": envelope}, {"role": "user", "content": prompt}]


def _extract_content(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return ""
    message = choices[0].get("message")
    if isinstance(message, Mapping) and isinstance(message.get("content"), str):
        return str(message["content"])
    return str(choices[0].get("text", "")) if isinstance(choices[0].get("text"), str) else ""


def _extract_tool_calls(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return []
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        return []
    calls = message.get("tool_calls")
    return [item for item in calls if isinstance(item, Mapping)] if isinstance(calls, list) else []


def _usage(response: Mapping[str, Any]) -> tuple[int | None, int | None, float | None]:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return None, None, None
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens")
    completion = usage.get("completion_tokens") or usage.get("output_tokens")
    cost = usage.get("cost")
    return (
        int(prompt) if isinstance(prompt, (int, float)) else None,
        int(completion) if isinstance(completion, (int, float)) else None,
        float(cost) if isinstance(cost, (int, float)) else None,
    )


def call_model(candidate: Candidate, task: Mapping[str, Any], context: str, store: SecretStore) -> tuple[Mapping[str, Any], float]:
    key = store.get(candidate.connection_id, candidate.provider)
    started = time.perf_counter()
    url = OPENROUTER_URL if candidate.provider == "openrouter" else GROQ_URL
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if candidate.provider == "openrouter":
        headers.update({"HTTP-Referer": "http://localhost", "X-Title": "AI-Agent Internal Model Benchmark"})
    payload: dict[str, Any] = {
        "model": candidate.model,
        "messages": build_messages(task, context),
        "temperature": 0,
        "stream": False,
    }
    if candidate.provider == "openrouter":
        payload["usage"] = {"include": True}
    if task.get("kind") == "tool":
        payload["tools"] = TOOL_DEFINITIONS
        payload["tool_choice"] = "required"
    if candidate.provider == "groq":
        payload["reasoning_effort"] = "medium" if candidate.model.endswith("120b") else "low"
    response = requests.post(url, headers=headers, json=payload, timeout=(10, 120))
    elapsed = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, Mapping):
        raise RuntimeError("Provider returned a non-object JSON response")
    return data, elapsed


def _json_object(text: str) -> tuple[dict[str, Any] | None, bool]:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None, False
    return (dict(value), True) if isinstance(value, Mapping) else (None, False)


def _contains_secret_like_value(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("sk-or-v1-", "gsk_", "openrouter_api_key", "groq_api_key", "bearer "))


def _executor(root: Path) -> TerminalExecutor:
    git = shutil.which("git")
    pytest = shutil.which("pytest")
    tools = [path for path in (git, pytest) if path]
    if len(tools) != 2:
        raise RuntimeError("Benchmark requires approved git and pytest executables")
    policy = WorkspaceResourcePolicy(root, allowed_tool_paths=tools)
    sandbox = ProcessSandbox(policy, timeout_seconds=180, max_output_chars=20_000)
    return TerminalExecutor(sandbox)


def _prepare_workspace(root: Path) -> tuple[Path, TerminalExecutor]:
    temp = Path(tempfile.mkdtemp(prefix="ai-agent-model-benchmark-"))
    ignore = shutil.ignore_patterns(".git", "benchmark_results.local.json", "__pycache__", ".pytest_cache")
    shutil.copytree(root, temp, dirs_exist_ok=True, ignore=ignore)
    executor = _executor(temp)
    for command in (("git", "init"), ("git", "add", "-A")):
        result = executor.run(command)
        if result.returncode != 0:
            shutil.rmtree(temp, ignore_errors=True)
            raise RuntimeError(f"Disposable benchmark workspace setup failed: {command[0]}")
    return temp, executor


def _run_verification(executor: TerminalExecutor, task: Mapping[str, Any]) -> bool:
    for raw in task.get("verification", []):
        try:
            args = shlex.split(str(raw), posix=True)
        except ValueError:
            return False
        if not args or Path(args[0]).name.lower().removesuffix(".exe") != "pytest":
            return False
        result = executor.run(tuple(args), target_paths=tuple(str(p) for p in task.get("target_paths", [])))
        if result.returncode != 0 or result.timed_out:
            return False
    return True


def _apply_patch(executor: TerminalExecutor, root: Path, patch_text: str, allowed_paths: set[str]) -> tuple[bool, set[str]]:
    if not patch_text.strip():
        return False, set()
    patch_file = root / ".benchmark.patch"
    patch_file.write_text(patch_text, encoding="utf-8")
    try:
        check = executor.run(("git", "apply", "--check", str(patch_file)))
        if check.returncode != 0:
            return False, set()
        applied = executor.run(("git", "apply", str(patch_file)))
        if applied.returncode != 0:
            return False, set()
        changed_result = executor.run(("git", "diff", "--name-only"))
        if changed_result.returncode != 0:
            return False, set()
        changed = {line.strip().replace("\\", "/") for line in changed_result.stdout.splitlines() if line.strip()}
        if not changed.issubset(allowed_paths):
            return False, changed
        return True, changed
    finally:
        patch_file.unlink(missing_ok=True)


def _work_product_compatible(task: Mapping[str, Any], parsed: Mapping[str, Any]) -> bool:
    if task.get("class") not in {"COMPLEX", "MEDIUM", "LEADER"}:
        return True
    if task.get("kind") not in {"code", "agentic"}:
        return True
    required = {"summary", "rationale", "touched_paths", "unified_diff"}
    return required.issubset(parsed.keys())


def evaluate(task: Mapping[str, Any], response: Mapping[str, Any], latency_ms: float, executor: TerminalExecutor | None, root: Path | None) -> tuple[float, dict[str, float], bool, bool, bool, bool, str | None]:
    content = _extract_content(response)
    parsed, structured_ok = _json_object(content)
    tool_calls = _extract_tool_calls(response)
    error: str | None = None
    tool_ok = True
    regression_ok = True
    work_product_ok = True

    if _contains_secret_like_value(content):
        error = "response contained secret-like material"

    kind = str(task.get("kind", "leader"))
    if kind == "tool":
        if not tool_calls:
            tool_ok = False
        else:
            function = tool_calls[0].get("function")
            tool_ok = isinstance(function, Mapping) and function.get("name") in {"read_context_file", "record_evidence"}
        structured_ok = tool_ok and isinstance(content, str) and content.strip() in {"", "null"}
        parsed = parsed or {}
    elif parsed is None:
        error = error or "response was not valid JSON"
        structured_ok = False
        parsed = {}

    required = {"classification", "objective", "plan", "validation", "stop_conditions"}
    if kind in {"leader", "structured", "agentic", "tool"}:
        coverage = len(required & parsed.keys()) / len(required)
        correctness = 30 * coverage
        reasoning = 15 * coverage
        solution_quality = 15 * min(1.0, (len(parsed.get("plan", [])) if isinstance(parsed.get("plan"), list) else 0) / 2)
    else:
        touched = parsed.get("touched_paths")
        patch = parsed.get("unified_diff")
        allowed = {str(path).replace("\\", "/") for path in task.get("target_paths", [])}
        if executor is None or root is None or not isinstance(touched, list):
            apply_ok, changed = False, set()
        else:
            apply_ok, changed = _apply_patch(executor, root, str(patch or ""), allowed)
        scope_ok = apply_ok and {str(path).replace("\\", "/") for path in touched} == changed
        regression_ok = _run_verification(executor, task) if apply_ok and executor is not None else False
        correctness = 30 if apply_ok and regression_ok else 15 if apply_ok else 0
        solution_quality = 15 if scope_ok else 7 if apply_ok else 0
        reasoning = 15 if isinstance(parsed.get("rationale"), str) and parsed.get("rationale", "").strip() else 0
        work_product_ok = _work_product_compatible(task, parsed)
        if not work_product_ok:
            error = error or "response was not compatible with the benchmark WorkerWorkProduct envelope"

    instruction_adherence = 10 if structured_ok and error is None else 0
    tool_structured = 10 if (tool_ok if kind == "tool" else structured_ok) else 0
    regression_safety = 10 if regression_ok and error is None else 0
    latency = max(0.0, min(5.0, 5.0 * (1.0 - max(0.0, latency_ms - 5000) / 55000)))
    dimensions = {
        "correctness": correctness,
        "solution_quality": solution_quality,
        "reasoning": reasoning,
        "instruction_adherence": instruction_adherence,
        "tool_structured": tool_structured,
        "regression_safety": regression_safety,
        "latency": latency,
        "reliability": 0,
    }
    return sum(dimensions.values()), dimensions, structured_ok, tool_ok, regression_ok, work_product_ok, error


def candidate_from_args(provider: str, model: str, connection_id: str) -> Candidate:
    allowed_models = OPENROUTER_CANDIDATES if provider == "openrouter" else GROQ_CANDIDATES
    allowed_ids = OPENROUTER_IDS if provider == "openrouter" else GROQ_IDS
    if model not in allowed_models:
        raise ValueError(f"Model is outside the benchmark shortlist: {model}")
    if connection_id not in allowed_ids:
        raise ValueError(f"Connection ID is outside the benchmark pool: {connection_id}")
    return Candidate(provider, model, connection_id)


def run_benchmark(root: Path, candidates: list[Candidate], repeats: int, selected_classes: set[str] | None = None) -> list[RunResult]:
    corpus = load_corpus()
    tasks = [task for task in corpus["tasks"] if not selected_classes or task["class"] in selected_classes]
    store = WindowsProtectedSecretStore()
    results: list[RunResult] = []
    for candidate in candidates:
        for task in tasks:
            for repeat in range(1, repeats + 1):
                temp_root: Path | None = None
                executor: TerminalExecutor | None = None
                started = time.perf_counter()
                try:
                    context = read_context(task, root)
                    response, latency_ms = call_model(candidate, task, context, store)
                    if task.get("kind") == "code":
                        temp_root, executor = _prepare_workspace(root)
                    score, dimensions, structured_ok, tool_ok, regression_ok, work_product_ok, error = evaluate(task, response, latency_ms, executor, temp_root)
                    in_tokens, out_tokens, cost = _usage(response)
                    results.append(RunResult(candidate, str(task["id"]), str(task["class"]), repeat, error is None and score > 0, score, dimensions, latency_ms, in_tokens, out_tokens, cost, structured_ok, tool_ok, regression_ok, work_product_ok, error))
                except Exception as exc:
                    results.append(RunResult(candidate, str(task["id"]), str(task["class"]), repeat, False, 0.0, {key: 0.0 for key in SCORE_WEIGHTS}, (time.perf_counter() - started) * 1000, None, None, None, False, False, False, False, f"{type(exc).__name__}: {exc}"))
                finally:
                    if temp_root is not None:
                        shutil.rmtree(temp_root, ignore_errors=True)
    return results


def aggregate(results: list[RunResult]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[RunResult]] = {}
    for result in results:
        grouped.setdefault((result.candidate.model, result.task_class), []).append(result)
    output: dict[str, Any] = {}
    for (model, task_class), items in grouped.items():
        dims = {key: sum(item.dimensions[key] for item in items) / len(items) for key in SCORE_WEIGHTS}
        success_rate = sum(1 for item in items if item.ok) / len(items)
        work_product_rate = sum(1 for item in items if item.work_product_compatible) / len(items)
        dims["reliability"] = 5 * success_rate
        output[f"{model}::{task_class}"] = {
            "score_out_of_100": round(sum(dims.values()), 2),
            "dimensions": {key: round(value, 2) for key, value in dims.items()},
            "mean_latency_ms": round(sum(item.latency_ms for item in items) / len(items), 2),
            "success_rate": round(success_rate, 4),
            "work_product_compatibility_rate": round(work_product_rate, 4),
            "input_tokens": sum(item.input_tokens or 0 for item in items),
            "output_tokens": sum(item.output_tokens or 0 for item in items),
            "cost_usd": round(sum(item.cost_usd or 0 for item in items), 6),
        }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Project-specific model benchmark; no production routing mutation.")
    parser.add_argument("--repo-root", type=Path, default=BASE_DIR)
    parser.add_argument("--provider", choices=["openrouter", "groq"], action="append")
    parser.add_argument("--model", action="append")
    parser.add_argument("--connection-id", action="append")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--class", dest="classes", action="append", choices=["SIMPLE", "MEDIUM", "COMPLEX", "LEADER"])
    parser.add_argument("--output", type=Path, default=BASE_DIR / "benchmark_results.local.json")
    args = parser.parse_args()

    models = args.model or []
    ids = args.connection_id or []
    providers = args.provider or []
    if not models or len(models) != len(ids):
        raise SystemExit("Provide --model and --connection-id once per candidate.")
    if len(providers) not in {1, len(models)}:
        raise SystemExit("Provide one --provider for all candidates or one per candidate.")
    candidates: list[Candidate] = []
    for index, model in enumerate(models):
        provider = providers[index] if len(providers) == len(models) else providers[0]
        candidates.append(candidate_from_args(provider, model, ids[index]))

    results = run_benchmark(args.repo_root.resolve(), candidates, max(1, args.repeats), set(args.classes) if args.classes else None)
    payload = {
        "benchmark_version": 2,
        "production_registry_mutated": False,
        "routing_policy_mutated": False,
        "raw_credentials_returned": False,
        "candidates": [candidate.__dict__ for candidate in candidates],
        "results": [item.to_dict() for item in results],
        "aggregate": aggregate(results),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload["aggregate"], indent=2, ensure_ascii=False))
    print(f"Results written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
