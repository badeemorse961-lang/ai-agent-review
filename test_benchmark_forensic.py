from __future__ import annotations

import json
from types import SimpleNamespace

import benchmark_forensic
import model_benchmark as benchmark


def test_safe_redaction_removes_secret_like_values() -> None:
    value = {
        "Authorization": "Bearer this-is-secret-like-abcdefghijklmnopqrstuvwxyz",
        "nested": "sk-or-v1-example-secret",
        "plain": "safe",
    }
    safe = benchmark_forensic.safe(value)
    assert safe["Authorization"] == "[REDACTED]"
    assert safe["nested"] == "[REDACTED]"
    assert safe["plain"] == "safe"


def test_exception_evidence_is_diagnostic_and_secret_safe() -> None:
    exc = RuntimeError("Authorization: Bearer sk-or-v1-super-secret-value")
    evidence = benchmark_forensic.exception_evidence(exc, "inference.call_model")
    assert evidence["phase"] == "inference.call_model"
    assert evidence["function"] == "collect_task"
    assert evidence["exception_type"] == "RuntimeError"
    assert "forensic collector exception" not in evidence["exception_message"]
    assert "sk-or-v1-" not in evidence["exception_message"]
    assert "Bearer" not in "\n".join(evidence["traceback"])


def test_collect_task_exception_preserves_safe_partial_evidence(monkeypatch, tmp_path) -> None:
    task = {
        "id": "S1",
        "class": "SIMPLE",
        "kind": "code",
        "expected": {},
        "verification": ["python -m pytest -q test_calculator.py"],
        "target_paths": ["test_calculator.py"],
    }
    candidate = benchmark.Candidate("openrouter", "openai/gpt-5.6-luna", "OR-01")

    def fail_call_model(*_args, **_kwargs):
        raise UnboundLocalError("cannot access local variable 'response' where it is not associated with a value")

    monkeypatch.setattr(benchmark, "_prepare_workspace", lambda _root: (tmp_path, SimpleNamespace()))
    monkeypatch.setattr(benchmark, "read_context", lambda *_args, **_kwargs: "safe context")
    monkeypatch.setattr(benchmark, "call_model", fail_call_model)
    monkeypatch.setattr(benchmark, "WindowsProtectedSecretStore", lambda: object())
    result = benchmark_forensic.collect_task(tmp_path, task, candidate)
    assert result["error_type"] == "UnboundLocalError"
    assert result["error"] == "forensic collector failed"
    assert result["forensic_status"] == "EVALUATOR_FAILURE"
    assert result["forensic_exception"]["phase"] == "inference.call_model"
    assert "response" in result["forensic_exception"]["exception_message"]
    assert result["forensic_exception"]["traceback"]


def test_collect_task_successful_collection_remains_successful(monkeypatch, tmp_path) -> None:
    task = {
        "id": "S1",
        "class": "SIMPLE",
        "kind": "code",
        "expected": {},
        "verification": ["python -m pytest -q test_calculator.py"],
        "target_paths": ["test_calculator.py"],
    }
    candidate = benchmark.Candidate("openrouter", "openai/gpt-5.6-luna", "OR-01")
    response = {
        "choices": [{"message": {"content": json.dumps({
            "summary": "add focused regression test",
            "rationale": "bounded test-only change",
            "touched_paths": ["test_calculator.py"],
            "unified_diff": "--- a/test_calculator.py\n+++ b/test_calculator.py\n@@ -1 +1 @@\n-old\n+new\n",
        })}}],
    }
    tool_trace = benchmark.ToolTrace(False, 0, None, True, True, True, False)

    class FakeExecutor:
        def run(self, *_args, **_kwargs):
            raise AssertionError("verification should be stubbed in this unit test")

    monkeypatch.setattr(benchmark, "_prepare_workspace", lambda _root: (tmp_path, FakeExecutor()))
    monkeypatch.setattr(benchmark, "read_context", lambda *_args, **_kwargs: "safe context")
    monkeypatch.setattr(benchmark, "call_model", lambda *_args, **_kwargs: (response, 12.5, tool_trace, (10, 8, 0.001)))
    monkeypatch.setattr(benchmark, "WindowsProtectedSecretStore", lambda: object())
    monkeypatch.setattr(benchmark, "_apply_patch", lambda *_args, **_kwargs: (True, {"test_calculator.py"}))
    monkeypatch.setattr(benchmark, "_run_verification", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(benchmark, "_code_assertions", lambda *_args, **_kwargs: (True, []))
    result = benchmark_forensic.collect_task(tmp_path, task, candidate)
    assert result["model_response_received"] is True
    assert result["structured_ok"] is True
    assert result["changed_paths"] == ["test_calculator.py"]
    assert result["verification"]["executed"] is False
    assert "forensic_exception" not in result
    assert result["forensic_status"] == "UNRESOLVED"


def test_verification_evidence_records_original_normalized_exit_and_output() -> None:
    task = {"verification": ["python -m pytest -q test_calculator.py"], "target_paths": ["test_calculator.py"]}
    tracer = benchmark_forensic.TracingExecutor(SimpleNamespace())
    tracer.events.append({"command": ("pytest", "-q", "test_calculator.py"), "executed": True, "returncode": 0, "timed_out": False, "stdout": "1 passed", "stderr": ""})
    evidence = benchmark_forensic.verification_evidence(task, tracer)
    assert evidence["original_commands"] == ["python -m pytest -q test_calculator.py"]
    assert evidence["normalized_command"] == ["pytest", "-q", "test_calculator.py"]
    assert evidence["terminal_executor_executable"] == "pytest"
    assert evidence["returncode"] == 0
    assert evidence["timed_out"] is False
    assert evidence["stdout"] == "1 passed"


def test_semantic_details_report_expected_vs_actual() -> None:
    task = {"expected": {"classification": "PLAN"}}
    parsed = {"classification": "EXECUTE"}
    details = benchmark_forensic.semantic_details(task, parsed, ["classification_mismatch"])
    assert details == [{"code": "classification_mismatch", "expected": "PLAN", "actual": "EXECUTE"}]


def test_tool_trace_capture_is_bounded_and_secret_safe(tmp_path) -> None:
    task = {"context_files": ["PROJECT_RULES.md"], "expected": {"allowed_tools": ["read_context_file"]}}
    (tmp_path / "PROJECT_RULES.md").write_text("safe context", encoding="utf-8")
    result, ok = benchmark._tool_result("read_context_file", {"path": "PROJECT_RULES.md"}, task, tmp_path)
    safe_result = benchmark_forensic.safe(json.loads(result))
    assert ok is True
    assert "safe context" in safe_result["content"]
    assert "sk-or-v1-" not in json.dumps(safe_result)
    assert "authorization" not in json.dumps(safe_result).lower()


def test_forensic_helpers_do_not_change_scoring_semantics() -> None:
    task = {
        "class": "SIMPLE",
        "kind": "leader",
        "expected": {
            "classification": "PLAN",
            "required_fields": {"classification": "string", "objective": "string", "plan": "list", "validation": "any", "stop_conditions": "any", "evidence": "object_or_list"},
            "required_planning_properties": [],
            "required_stop_conditions": [],
            "required_evidence_fields": [],
        },
    }
    parsed = {"classification": "PLAN", "objective": "bounded", "plan": ["inspect"], "validation": "check", "stop_conditions": ["stop"], "evidence": {"scope": "bounded"}}
    response = {"choices": [{"message": {"content": json.dumps(parsed)}}]}
    baseline = benchmark.evaluate(task, response, 10.0, None, None, benchmark.ToolTrace(False, 0, None, True, True, True))
    semantic_ok, semantic_failures = benchmark._semantic_assertions(task, parsed)
    assert semantic_ok is True
    assert semantic_failures == []
    assert baseline[0] > 0
    assert baseline[2] is True
