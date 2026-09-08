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
