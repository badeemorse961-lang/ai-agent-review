from __future__ import annotations

import argparse
import json
import re
import shutil
import tempfile
import traceback
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

import model_benchmark as benchmark


SECRET_KEYS = re.compile(r"(?:api[_-]?key|authorization|credential|password|secret|token)", re.IGNORECASE)
SECRET_VALUES = (
    re.compile(r"sk-or-v1-[A-Za-z0-9_-]+", re.IGNORECASE),
    re.compile(r"gsk_[A-Za-z0-9_-]+", re.IGNORECASE),
    re.compile(r"authorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(r"\bbearer\s+[A-Za-z0-9._-]{20,}", re.IGNORECASE),
)
MAX_TEXT = 4000
MAX_TRACEBACK_LINES = 12


def safe(value: Any, *, key: str | None = None) -> Any:
    if key and SECRET_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): safe(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [safe(item) for item in value]
    if isinstance(value, tuple):
        return [safe(item) for item in value]
    if isinstance(value, str):
        text = value
        for pattern in SECRET_VALUES:
            text = pattern.sub("[REDACTED]", text)
        return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "\n[FORENSIC OUTPUT TRUNCATED]"
    return value


def exception_evidence(exc: BaseException, phase: str) -> dict[str, Any]:
    trace_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    trace_lines = [safe(line).rstrip() for line in trace_lines][-MAX_TRACEBACK_LINES:]
    return {
        "phase": phase,
        "function": "collect_task",
        "exception_type": type(exc).__name__,
        "exception_message": safe(str(exc)) or "[NO MESSAGE]",
        "traceback": trace_lines,
    }


class TracingExecutor:
    """Records calls while delegating to the existing TerminalExecutor unchanged."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.events: list[dict[str, Any]] = []

    def run(self, command, *, target_paths=(), external_reads=(), external_writes=()):
        event = {"command": tuple(map(str, command)), "target_paths": [str(p) for p in target_paths]}
        try:
            result = self.inner.run(
                command,
                target_paths=target_paths,
                external_reads=external_reads,
                external_writes=external_writes,
            )
        except Exception as exc:
            event.update(
                {
                    "executed": False,
                    "exception_type": type(exc).__name__,
                    "exception_message": safe(str(exc)),
                }
            )
            self.events.append(event)
            raise
        event.update(
            {
                "executed": True,
                "returncode": result.returncode,
                "timed_out": result.timed_out,
                "stdout": safe(result.stdout),
                "stderr": safe(result.stderr),
            }
        )
        self.events.append(event)
        return result


def semantic_details(task: Mapping[str, Any], parsed: Mapping[str, Any], failures: list[str]) -> list[dict[str, Any]]:
    expected = task.get("expected", {})
    details: list[dict[str, Any]] = []
    for code in failures:
        item: dict[str, Any] = {"code": code}
        if code == "classification_mismatch":
            item.update(expected=expected.get("classification"), actual=parsed.get("classification"))
        elif code.startswith("required_field_missing:"):
            field = code.split(":", 1)[1]
            item.update(expected=expected.get("required_fields", {}).get(field), actual="<missing>")
        elif code.startswith("required_field_invalid:"):
            field = code.split(":", 1)[1]
            item.update(expected=expected.get("required_fields", {}).get(field), actual=safe(parsed.get(field)))
        elif code.startswith("missing_planning_property:"):
            item.update(expected=code.split(":", 1)[1], actual=safe(parsed.get("plan")))
        elif code.startswith("missing_stop_condition:"):
            item.update(expected=code.split(":", 1)[1], actual=safe(parsed.get("stop_conditions")))
        elif code.startswith("evidence_missing:"):
            item.update(expected=code.split(":", 1)[1], actual=safe(parsed.get("evidence")))
        elif code.startswith("missing:"):
            item.update(expected=code.split(":", 1)[1], actual=safe(parsed))
        elif code.startswith("forbidden_safety:") or code.startswith("forbidden:"):
            item.update(expected="forbidden term", actual=safe(parsed))
        elif code.startswith("dependency_order_violation:"):
            item.update(expected=code.split(":", 1)[1], actual=safe(parsed.get("dependencies", parsed.get("plan"))))
        elif code.startswith("path_mismatch:"):
            path = code.split(":", 1)[1]
            item.update(expected=safe(benchmark._value_at_path(expected, path)), actual=safe(benchmark._value_at_path(parsed, path)))
        elif code.startswith("path_missing:"):
            _, path, term = code.split(":", 2)
            item.update(expected=term, actual=safe(benchmark._value_at_path(parsed, path)))
        elif code.startswith("path_forbidden:"):
            _, path, term = code.split(":", 2)
            item.update(expected=f"must not contain {term}", actual=safe(benchmark._value_at_path(parsed, path)))
        else:
            item.update(expected=None, actual=None)
        details.append(item)
    return details


def verification_evidence(task: Mapping[str, Any], tracer: TracingExecutor) -> dict[str, Any]:
    original = [str(v) for v in task.get("verification", [])]
    event = tracer.events[-1] if tracer.events else None
    return {
        "original_commands": original,
        "normalized_command": list(event["command"]) if event else None,
        "terminal_executor_executable": event["command"][0] if event else None,
        "executed": bool(event and event.get("executed")),
        "returncode": event.get("returncode") if event else None,
        "timed_out": event.get("timed_out") if event else None,
        "stdout": event.get("stdout", "") if event else "",
        "stderr": event.get("stderr", "") if event else "",
        "exception_type": event.get("exception_type") if event else None,
        "exception_message": event.get("exception_message") if event else None,
    }


def classify(response_received: bool, semantic_failures: list[str], hard_failures: list[str], verification: dict[str, Any] | None) -> str:
    if verification is not None and not verification["executed"]:
        return "EVALUATOR_FAILURE" if response_received else "UNRESOLVED"
    if semantic_failures or hard_failures:
        return "MODEL_FAILURE"
    if verification is not None and (verification["returncode"] != 0 or verification["timed_out"]):
        return "MODEL_FAILURE"
    return "UNRESOLVED"


def _partial_safe_response(response: Any) -> tuple[bool, dict[str, Any]]:
    if not isinstance(response, Mapping):
        return False, {}
    received = bool(response.get("choices"))
    parsed, _ = benchmark._json_object(benchmark._extract_content(response))
    return received, safe(parsed or {})


def collect_task(root: Path, task: Mapping[str, Any], candidate: benchmark.Candidate) -> dict[str, Any]:
    temp_root: Path | None = None
    tracer: TracingExecutor | None = None
    tool_calls: list[Any] = []
    tool_results: list[Any] = []
    phase = "collect_task.start"
    response: Mapping[str, Any] | None = None
    parsed: dict[str, Any] = {}
    structured_ok = False
    changed: set[str] = set()
    semantic_failures: list[str] = []
    tool_trace: Any = None
    usage: tuple[int | None, int | None, float | None] = (None, None, None)
    latency_ms: float | None = None
    work_product_ok = False
    kind = str(task.get("kind", "leader"))
    try:
        phase = "workspace.prepare"
        temp_root, executor = benchmark._prepare_workspace(root)
        tracer = TracingExecutor(executor)

        phase = "context.read"
        context = benchmark.read_context(task, root)
        original_post = benchmark.requests.post
        original_tool_result = benchmark._tool_result

        def capture_post(*args, **kwargs):
            capture_phase = "inference.response_capture"
            try:
                provider_response = original_post(*args, **kwargs)
                payload = provider_response.json()
                if isinstance(payload, Mapping):
                    calls = benchmark._extract_tool_calls(payload)
                    if calls:
                        tool_calls.extend(safe(calls))
                return provider_response
            except Exception:
                nonlocal phase
                phase = capture_phase
                raise

        def capture_tool_result(name, arguments, task_arg, root_arg):
            nonlocal phase
            phase = "tool.result_capture"
            result = original_tool_result(name, arguments, task_arg, root_arg)
            tool_results.append(safe(result))
            return result

        phase = "inference.call_model"
        with patch.object(benchmark.requests, "post", side_effect=capture_post), patch.object(benchmark, "_tool_result", side_effect=capture_tool_result):
            response, latency_ms, tool_trace, usage = benchmark.call_model(
                candidate, task, context, benchmark.WindowsProtectedSecretStore(), temp_root
            )

        phase = "response.parse"
        parsed, structured_ok = benchmark._json_object(benchmark._extract_content(response))
        parsed = parsed or {}
        work_product_ok = benchmark._work_product_compatible(task, parsed)

        phase = "evaluation.semantic"
        if kind in {"leader", "structured", "tool"}:
            _, semantic_failures = benchmark._semantic_assertions(task, parsed)
            semantic_failures.extend(benchmark._validate_required_fields(task, parsed))
            if kind == "tool" and not (
                tool_trace.tool_calls_seen == 1
                and tool_trace.selected_tool is not None
                and tool_trace.arguments_valid
                and tool_trace.execution_ok
                and tool_trace.continuation_ok
                and not tool_trace.unsafe_tool
            ):
                semantic_failures.append("tool_loop_failed")
        else:
            phase = "evaluation.patch"
            touched = parsed.get("touched_paths")
            patch = parsed.get("unified_diff")
            apply_ok = False
            if isinstance(touched, list):
                apply_ok, changed = benchmark._apply_patch(executor, temp_root, str(patch or ""))
            allowed = {benchmark._normalise_path(str(p)) for p in task.get("target_paths", [])}
            touched_normalised = {benchmark._normalise_path(str(p)) for p in touched} if isinstance(touched, list) else set()
            scope_ok = apply_ok and touched_normalised == changed and changed <= allowed
            phase = "evaluation.verification"
            regression_ok = benchmark._run_verification(tracer, task) if apply_ok else False
            _, code_failures = benchmark._code_assertions(task, parsed, temp_root, changed)
            semantic_failures.extend(benchmark._validate_required_fields(task, parsed))
            semantic_failures.extend(code_failures)
            if not apply_ok:
                semantic_failures.append("patch_not_applied")
            if not regression_ok:
                semantic_failures.append("focused_verification_failed")
            if not scope_ok:
                semantic_failures.append("touched_paths_mismatch")

        phase = "evaluation.hard_failures"
        hard_failures = benchmark._hard_failures(task, parsed, semantic_failures, tool_trace, structured_ok, work_product_ok, changed)
        verification = verification_evidence(task, tracer) if kind in {"code", "agentic"} else None
        response_received = isinstance(response, Mapping) and bool(response.get("choices"))
        return {
            "task_id": str(task["id"]),
            "kind": kind,
            "model_response_received": response_received,
            "parsed_response": safe(parsed),
            "structured_ok": structured_ok,
            "work_product_ok": work_product_ok,
            "changed_paths": sorted(changed),
            "touched_paths": safe(parsed.get("touched_paths")),
            "semantic_failures": semantic_failures,
            "semantic_failure_details": semantic_details(task, parsed, semantic_failures),
            "hard_failures": hard_failures,
            "verification": verification,
            "tool_trace": {
                "requested": tool_trace.requested,
                "tool_calls_seen": tool_trace.tool_calls_seen,
                "selected_tool": tool_trace.selected_tool,
                "arguments_valid": tool_trace.arguments_valid,
                "execution_ok": tool_trace.execution_ok,
                "continuation_ok": tool_trace.continuation_ok,
                "unsafe_tool": tool_trace.unsafe_tool,
                "model_tool_calls": tool_calls,
                "tool_results": tool_results,
            },
            "expected_assertions": safe(task.get("expected", {})),
            "usage": {"input_tokens": usage[0], "output_tokens": usage[1], "cost_usd": usage[2]},
            "latency_ms": latency_ms,
            "forensic_status": classify(response_received, semantic_failures, hard_failures, verification),
        }
    except Exception as exc:
        phase_evidence = exception_evidence(exc, phase)
        response_received, safe_parsed = _partial_safe_response(response)
        verification = verification_evidence(task, tracer) if tracer else None
        partial_tool_trace = None
        if tool_trace is not None:
            partial_tool_trace = {
                "requested": tool_trace.requested,
                "tool_calls_seen": tool_trace.tool_calls_seen,
                "selected_tool": tool_trace.selected_tool,
                "arguments_valid": tool_trace.arguments_valid,
                "execution_ok": tool_trace.execution_ok,
                "continuation_ok": tool_trace.continuation_ok,
                "unsafe_tool": tool_trace.unsafe_tool,
                "model_tool_calls": tool_calls,
                "tool_results": tool_results,
            }
        return {
            "task_id": str(task["id"]),
            "kind": kind,
            "model_response_received": response_received,
            "parsed_response": safe_parsed,
            "structured_ok": structured_ok,
            "work_product_ok": work_product_ok,
            "changed_paths": sorted(changed),
            "touched_paths": safe(parsed.get("touched_paths")) if parsed else None,
            "semantic_failures": semantic_failures,
            "semantic_failure_details": semantic_details(task, parsed, semantic_failures),
            "hard_failures": [],
            "verification": verification,
            "tool_trace": partial_tool_trace,
            "expected_assertions": safe(task.get("expected", {})),
            "error_type": phase_evidence["exception_type"],
            "error": "forensic collector failed",
            "forensic_exception": phase_evidence,
            "forensic_status": "EVALUATOR_FAILURE",
        }
    finally:
        if temp_root is not None:
            shutil.rmtree(temp_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Single-candidate benchmark forensic evidence capture.")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--provider", choices=["openrouter", "groq"], default="openrouter")
    parser.add_argument("--model", default="openai/gpt-5.6-luna")
    parser.add_argument("--connection-id", default="OR-01")
    parser.add_argument("--class", dest="task_class", choices=["SIMPLE"], default="SIMPLE")
    parser.add_argument("--repeats", type=int, choices=[1], default=1)
    parser.add_argument("--output", type=Path, default=Path(tempfile.gettempdir()) / "ai-agent-model-benchmark-forensic.json")
    args = parser.parse_args()
    if (args.provider, args.model, args.connection_id, args.repeats) != ("openrouter", "openai/gpt-5.6-luna", "OR-01", 1):
        raise SystemExit("Forensic runner is restricted to OR-01 / openai/gpt-5.6-luna / repeats=1")
    candidate = benchmark.candidate_from_args(args.provider, args.model, args.connection_id)
    corpus = benchmark.load_corpus()
    tasks = [task for task in corpus["tasks"] if task.get("class") == args.task_class]
    payload = {
        "benchmark_version": corpus.get("version"),
        "mode": "forensic_single_smoke",
        "candidate": candidate.__dict__,
        "tasks": [collect_task(args.repo_root.resolve(), task, candidate) for task in tasks],
        "production_registry_mutated": False,
        "routing_policy_mutated": False,
        "allocation_mutated": False,
        "dynamic_onboarding_mutated": False,
        "raw_credentials_returned": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"Forensic artifact written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())