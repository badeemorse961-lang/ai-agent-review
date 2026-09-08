from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import requests

from protected_secret_store import SecretStore, WindowsProtectedSecretStore


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

OPENROUTER_IDS = {"OR-01", "OR-02", "OR-03", "OR-04", "OR-05", "OR-06", "OR-07", "OR-08", "OR-09", "OR-10", "OR-11"}
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
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.candidate.provider,
            "model": self.candidate.model,
            "connection_id": self.candidate.connection_id,
            "task_id": self.task_id,
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
        "Return a single JSON object. Do not include markdown fences. "
        "For leader/structured tasks include: classification, objective, plan, validation, "
        "risks, stop_conditions, and evidence. For code tasks include: summary, rationale, "
        "touched_paths, and unified_diff. Never output secrets or credentials."
    )
    return [
        {"role": "system", "content": envelope},
        {"role": "user", "content": f"Task class: {task['class']}\nTask: {task['prompt']}\n\nRepository context:\n{context}"},
    ]


def _extract_content(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return ""
    message = choices[0].get("message")
    if isinstance(message, Mapping):
        content = message.get("content")
        if isinstance(content, str):
            return content
    text = choices[0].get("text")
    return text if isinstance(text, str) else ""


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


def _extract_api_key(store: SecretStore, connection_id: str, provider: str) -> str:
    return store.get(connection_id, provider)


def call_model(candidate: Candidate, task: Mapping[str, Any], context: str, store: SecretStore) -> tuple[Mapping[str, Any], float]:
    started = time.perf_counter()
    key = _extract_api_key(store, candidate.connection_id, candidate.provider)
    url = OPENROUTER_URL if candidate.provider == "openrouter" else GROQ_URL
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if candidate.provider == "openrouter":
        headers.update({"HTTP-Referer": "http://localhost", "X-Title": "AI-Agent Internal Model Benchmark"})

    task_kind = str(task.get("kind", "leader"))
    payload: dict[str, Any] = {
        "model": candidate.model,
        "messages": build_messages(task, context),
        "temperature": 0,
        "stream": False,
    }
    if candidate.provider == "openrouter":
        payload["usage"] = {"include": True}
    if task_kind == "tool":
        payload["tools"] = TOOL_DEFINITIONS
        payload["tool_choice"] = "auto"
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
    forbidden = ("sk-or-v1-", "gsk_", "openrouter_api_key", "groq_api_key", "bearer ")
    return any(marker in lowered for marker in forbidden)


def _run_verification(root: Path, commands: list[str]) -> bool:
    for command in commands:
        # Verification commands are benchmark-authored, never model-authored.
        if not command.startswith("python -m pytest"):
            return False
        completed = subprocess.run(command, cwd=root, shell=True, capture_output=True, text=True, timeout=180)
        if completed.returncode != 0:
            return False
    return True


def _apply_patch(root: Path, patch_text: str, allowed_paths: set[str]) -> tuple[bool, set[str]]:
    if not patch_text.strip():
        return False, set()
    patch_file = root / ".benchmark.patch"
    patch_file.write_text(patch_text, encoding="utf-8")
    try:
        check = subprocess.run(["git", "apply", "--check", str(patch_file)], cwd=root, capture_output=True, text=True, timeout=30)
        if check.returncode != 0:
            return False, set()
        subprocess.run(["git", "apply", str(patch_file)], cwd=root, check=True, capture_output=True, text=True, timeout=30)
        changed = subprocess.check_output(["git", "diff", "--name-only"], cwd=root, text=True, timeout=30).splitlines()
        changed_set = {line.replace("\\", "/") for line in changed}
        if not changed_set.issubset(allowed_paths):
            return False, changed_set
        return True, changed_set
    finally:
        patch_file.unlink(missing_ok=True)


def evaluate(task: Mapping[str, Any], response: Mapping[str, Any], latency_ms: float, root: Path) -> tuple[float, dict[str, float], bool, bool, bool, str | None]:
    content = _extract_content(response)
    parsed, structured_ok = _json_object(content)
    tool_calls = _extract_tool_calls(response)
    tool_ok = True
    regression_ok = True
    error: str | None = None

    if parsed is None:
        error = "response was not valid JSON"
        dimensions = {"correctness": 0, "solution_quality": 0, "reasoning": 0, "instruction_adherence": 0, "tool_structured": 0, "regression_safety": 0, "latency": 0, "reliability": 0}
        return 0, dimensions, False, False, False, error

    if _contains_secret_like_value(content):
        error = "response contained secret-like material"

    kind = str(task.get("kind", "leader"))
    required = {"classification", "objective", "plan", "validation", "stop_conditions"}
    if kind in {"leader", "structured", "tool", "agentic"}:
        coverage = len(required & parsed.keys()) / len(required)
        reasoning = coverage * 15
        correctness = 30 if coverage == 1 else 30 * coverage
        solution_quality = 15 * min(1.0, len(parsed.get("plan", [])) / 2) if isinstance(parsed.get("plan"), list) else 5
    else:
        touched = parsed.get("touched_paths")
        patch = parsed.get("unified_diff")
        allowed = {str(path).replace("\\", "/") for path in task.get("target_paths", [])}
        apply_ok, changed = _apply_patch(root, str(patch or ""), allowed) if isinstance(touched, list) else (False, set())
        scope_ok = set(str(path).replace("\\", "/") for path in touched or []) == changed if apply_ok else False
        regression_ok = _run_verification(root, [str(command) for command in task.get("verification", [])]) if apply_ok else False
        correctness = 30 if apply_ok and regression_ok else 15 if apply_ok else 0
        solution_quality = 15 if scope_ok else 7 if apply_ok else 0
        reasoning = 15 if isinstance(parsed.get("rationale"), str) and parsed.get("rationale", "").strip() else 5

    instruction_adherence = 10 if structured_ok and error is None else 0
    if kind == "tool":
        if not tool_calls:
            tool_ok = False
        else:
            first = tool_calls[0]
            function = first.get("function")
            tool_ok = isinstance(function, Mapping) and function.get("name") in {"read_context_file", "record_evidence"}
        tool_structured = 10 if tool_ok else 0
    else:
        tool_structured = 10 if structured_ok else 0

    regression_safety = 10 if regression_ok and error is None else 0
    latency_score = max(0.0, min(5.0, 5.0 * (1.0 - max(0.0, latency_ms - 5000) / 55000)))
    dimensions = {
        "correctness": correctness,
        "solution_quality": solution_quality,
        "reasoning": reasoning,
        "instruction_adherence": instruction_adherence,
        "tool_structured": tool_structured,
        "regression_safety": regression_safety,
        "latency": latency_score,
        "reliability": 0,
    }
    return sum(dimensions.values()), dimensions, structured_ok, tool_ok, regression_ok, error


def _prepare_workspace(root: Path) -> Path:
    temp = Path(tempfile.mkdtemp(prefix="ai-agent-model-benchmark-"))
    archive = temp / "repo.tar"
    subprocess.run(["git", "archive", "--format=tar", "HEAD", "-o", str(archive)], cwd=root, check=True, timeout=30)
    subprocess.run(["tar", "-xf", str(archive)], cwd=temp, check=True, timeout=30)
    archive.unlink(missing_ok=True)
    return temp


def candidate_from_args(provider: str, model: str, connection_id: str) -> Candidate:
    allowed = OPENROUTER_CANDIDATES if provider == "openrouter" else GROQ_CANDIDATES
    if model not in allowed:
        raise ValueError(f"Model is outside the benchmark shortlist: {model}")
    allowed_ids = OPENROUTER_IDS if provider == "openrouter" else GROQ_IDS
    if connection_id not in allowed_ids:
        raise ValueError(f"Connection ID is outside the provider pool: {connection_id}")
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
                started = time.perf_counter()
                try:
                    context = read_context(task, root)
                    response, latency_ms = call_model(candidate, task, context, store)
                    temp_root = _prepare_workspace(root) if task.get("kind") == "code" else root
                    score, dimensions, structured_ok, tool_ok, regression_ok, error = evaluate(task, response, latency_ms, temp_root)
                    results.append(RunResult(candidate, str(task["id"]), repeat, error is None and score > 0, score, dimensions, latency_ms, *_usage(response), structured_ok, tool_ok, regression_ok, error))
                except Exception as exc:
                    results.append(RunResult(candidate, str(task["id"]), repeat, False, 0, {key: 0 for key in SCORE_WEIGHTS}, (time.perf_counter() - started) * 1000, None, None, None, False, False, False, f"{type(exc).__name__}: {exc}"))
                finally:
                    if temp_root is not None and temp_root != root:
                        shutil.rmtree(temp_root, ignore_errors=True)
    return results


def aggregate(results: list[RunResult]) -> dict[str, Any]:
    grouped: dict[str, list[RunResult]] = {}
    for result in results:
        grouped.setdefault(result.candidate.model, []).append(result)
    output: dict[str, Any] = {}
    for model, items in grouped.items():
        dims = {key: sum(item.dimensions[key] for item in items) / len(items) for key in SCORE_WEIGHTS}
        success_rate = sum(item.ok for item in items) / len(items)
        dims["reliability"] = 5 * success_rate
        total = sum(value for value in dims.values())
        output[model] = {
            "score_out_of_100": round(total, 2),
            "dimensions": {key: round(value, 2) for key, value in dims.items()},
            "mean_latency_ms": round(sum(item.latency_ms for item in items) / len(items), 2),
            "success_rate": round(success_rate, 4),
            "input_tokens": sum(item.input_tokens or 0 for item in items),
            "output_tokens": sum(item.output_tokens or 0 for item in items),
            "cost_usd": round(sum(item.cost_usd or 0 for item in items), 6),
        }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the AI-Agent project-specific model benchmark without mutating production configuration.")
    parser.add_argument("--repo-root", type=Path, default=BASE_DIR)
    parser.add_argument("--provider", choices=["openrouter", "groq"], action="append")
    parser.add_argument("--model", action="append")
    parser.add_argument("--connection-id", action="append")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--class", dest="classes", action="append", choices=["SIMPLE", "MEDIUM", "COMPLEX", "LEADER"])
    parser.add_argument("--output", type=Path, default=BASE_DIR / "benchmark_results.local.json")
    args = parser.parse_args()

    root = args.repo_root.resolve()
    providers = args.provider or ["openrouter", "groq"]
    models = args.model or []
    ids = args.connection_id or []
    if models and len(models) != len(ids):
        raise SystemExit("When --model is used, provide exactly one --connection-id for each model.")

    candidates: list[Candidate] = []
    if models:
        for index, model in enumerate(models):
            provider = providers[index] if len(providers) == len(models) else providers[0]
            candidates.append(candidate_from_args(provider, model, ids[index]))
    else:
        raise SystemExit("Specify candidate models explicitly; the runner never assumes a production connection.")

    results = run_benchmark(root, candidates, max(1, args.repeats), set(args.classes) if args.classes else None)
    payload = {
        "benchmark_version": 1,
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
