from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from model_benchmark import (
    Candidate,
    RunResult,
    SCORE_WEIGHTS,
    ToolTrace,
    _code_assertions,
    _contains_secret_like_value,
    _contains_term,
    _hard_failures,
    _prepare_workspace,
    _semantic_assertions,
    _tool_loop,
    _tool_result,
    _validate_required_fields,
    aggregate,
    load_corpus,
)


def _leader_payload() -> dict:
    return {
        "classification": "SAFE_STOP",
        "objective": "Act from repository evidence",
        "plan": [
            "separate observed evidence from hypotheses",
            "inspect provider transport and router health before deciding",
            "attempt recovery only after validation evidence",
        ],
        "validation": "validation evidence required",
        "stop_conditions": [
            "credential validity cannot be established",
            "authoritative assignment or authorization evidence is missing",
        ],
        "evidence": {
            "evidence": "observed provider failure",
            "failure history": "present",
            "validation result": "unknown",
            "authorization state": "unknown",
        },
    }


def test_corpus_has_explicit_expected_assertions_for_every_task() -> None:
    corpus = load_corpus()
    assert corpus["version"] == 2
    assert corpus["safety"]["production_registry_mutation"] is False
    assert corpus["safety"]["routing_policy_mutation"] is False
    assert corpus["safety"]["raw_credentials_allowed"] is False
    for task in corpus["tasks"]:
        expected = task.get("expected")
        assert isinstance(expected, dict), task["id"]
        assert expected, task["id"]
        if task["kind"] in {"leader", "structured", "tool", "agentic"}:
            assert expected.get("classification") is not None
            assert expected.get("required_fields")
            assert expected.get("required_stop_conditions")
            assert expected.get("required_evidence_fields")
        if task["kind"] in {"code", "agentic"} and task["id"] != "C4":
            assert expected.get("required_behavior")


def test_semantic_evaluation_rejects_wrong_classification_even_with_all_keys() -> None:
    task = next(item for item in load_corpus()["tasks"] if item["id"] == "M3")
    payload = _leader_payload()
    payload["classification"] = "APPROVE"
    semantic_pass, failures = _semantic_assertions(task, payload)
    assert not semantic_pass
    assert "classification_mismatch" in failures


def test_semantic_evaluation_requires_evidence_planning_and_stop_conditions() -> None:
    task = next(item for item in load_corpus()["tasks"] if item["id"] == "M3")
    payload = _leader_payload()
    payload["plan"] = ["do something"]
    payload["stop_conditions"] = []
    payload["evidence"] = {}
    semantic_pass, failures = _semantic_assertions(task, payload)
    assert not semantic_pass
    assert any(failure.startswith("missing_planning_property:") for failure in failures)
    assert any(failure.startswith("missing_stop_condition:") for failure in failures)
    assert any(failure.startswith("evidence_missing:") for failure in failures)


def test_unauthorized_approval_is_a_hard_fail_not_a_score_penalty() -> None:
    task = next(item for item in load_corpus()["tasks"] if item["id"] == "L3")
    payload = _leader_payload()
    payload["decision"] = "APPROVE"
    hard = _hard_failures(
        task,
        payload,
        [],
        ToolTrace(False, 0, None, True, True, True),
        True,
        True,
        set(),
    )
    assert "unauthorized_approval" in hard


def test_semantic_hard_assertion_is_not_mislabeled_as_approval() -> None:
    task = next(item for item in load_corpus()["tasks"] if item["id"] == "C3")
    hard = _hard_failures(
        task,
        _leader_payload(),
        ["classification_mismatch"],
        ToolTrace(False, 0, None, True, True, True),
        True,
        True,
        set(),
    )
    assert "semantic_hard_gate" in hard
    assert "unauthorized_approval" not in hard


def test_required_field_validation_is_type_aware() -> None:
    task = next(item for item in load_corpus()["tasks"] if item["id"] == "L1")
    payload = {"classification": "ANALYZE_PLAN", "objective": "x", "plan": "not-a-list"}
    failures = _validate_required_fields(task, payload)
    assert "required_field_invalid:plan" in failures
    assert "required_field_missing:validation" in failures


def test_term_matching_does_not_confuse_execute_with_execution() -> None:
    assert _contains_term({"text": "execution authorization is absent"}, "execute") is False
    assert _contains_term({"action": "EXECUTE"}, "execute") is True


def test_tool_result_enforces_approved_path_and_bounded_execution(tmp_path: Path) -> None:
    (tmp_path / "PROJECT_RULES.md").write_text("rules\n", encoding="utf-8")
    task = {"context_files": ["PROJECT_RULES.md"], "expected": {"allowed_tools": ["read_context_file"]}}
    text, ok = _tool_result("read_context_file", {"path": "PROJECT_RULES.md"}, task, tmp_path)
    assert ok
    assert json.loads(text)["ok"] is True
    _, unsafe = _tool_result("read_context_file", {"path": "secret.txt"}, task, tmp_path)
    assert unsafe is False


def test_tool_loop_executes_model_tool_result_model_continuation(tmp_path: Path) -> None:
    (tmp_path / "PROJECT_RULES.md").write_text("benchmark context\n", encoding="utf-8")
    task = next(item for item in load_corpus()["tasks"] if item["id"] == "S4")
    candidate = Candidate("openrouter", "openai/gpt-5.6-luna", "OR-01")
    first_payload = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "read_context_file", "arguments": '{"path":"PROJECT_RULES.md"}'},
                }],
            }
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    }
    second_payload = {
        "choices": [{"message": {
            "role": "assistant",
            "content": json.dumps({
                "classification": "PLAN",
                "objective": "Use PROJECT_RULES.md evidence",
                "plan": ["read the approved context file before deciding", "base the decision on the returned context", "return a bounded validation step"],
                "validation": "validate the decision against the returned context",
                "stop_conditions": ["tool output contradicts the requested scope", "the required context file cannot be read"],
                "evidence": {"path": "PROJECT_RULES.md", "result": "context returned"},
            }),
        }}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 9},
    }

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    calls = []

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"])
        return FakeResponse(first_payload if len(calls) == 1 else second_payload)

    store = SimpleNamespace(get=lambda *_: "protected-secret")
    with patch("model_benchmark.requests.post", side_effect=fake_post):
        response, latency, trace, usage = _tool_loop(candidate, task, "context", store, tmp_path)

    assert len(calls) == 2
    assert calls[0]["tool_choice"] == "required"
    assert calls[1]["messages"][-1]["role"] == "tool"
    assert calls[1]["messages"][-1]["content"]
    assert trace.tool_calls_seen == 1
    assert trace.selected_tool == "read_context_file"
    assert trace.arguments_valid is True
    assert trace.execution_ok is True
    assert trace.continuation_ok is True
    assert usage == (22, 13, None)
    assert "classification" in response["choices"][0]["message"]["content"]
    assert latency >= 0


def test_code_assertions_check_task_specific_expected_behavior(tmp_path: Path) -> None:
    path = tmp_path / "test_calculator.py"
    path.write_text("def test_add_negative_operands():\n    assert add(-2, 3) == 1\n", encoding="utf-8")
    task = {
        "expected": {
            "changed_paths_exact": ["test_calculator.py"],
            "required_file_contains": {"test_calculator.py": ["test_add_negative_operands", "assert add(-2, 3) == 1"]},
            "required_behavior": "adds a focused regression test",
        }
    }
    ok, failures = _code_assertions(task, {"touched_paths": ["test_calculator.py"]}, tmp_path, {"test_calculator.py"})
    assert ok
    assert failures == []


def _result(ok: bool, repeat: int, task_id: str = "S1") -> RunResult:
    candidate = Candidate("groq", "openai/gpt-oss-20b", "GROQ-02")
    dimensions = {key: 1.0 for key in SCORE_WEIGHTS}
    return RunResult(
        candidate=candidate,
        task_id=task_id,
        task_class="SIMPLE",
        repeat=repeat,
        ok=ok,
        semantic_pass=ok,
        hard_fail=not ok,
        hard_failure_codes=("semantic_hard_gate",) if not ok else (),
        score=50.0 if ok else 0.0,
        dimensions=dimensions,
        latency_ms=100.0,
        input_tokens=10,
        output_tokens=20,
        cost_usd=0.01,
        structured_ok=True,
        tool_ok=True,
        regression_ok=ok,
        work_product_compatible=True,
        reliability_score=5.0 if ok else 0.0,
        error=None,
    )


def test_aggregate_reports_task_metrics_repeat_consistency_and_failure_variance() -> None:
    results = [_result(True, 1), _result(False, 2), _result(True, 1, "S2"), _result(True, 2, "S2")]
    data = aggregate(results)["openai/gpt-oss-20b::SIMPLE"]
    assert data["tasks_total"] == 2
    assert data["tasks_passed"] == 1
    assert data["tasks_failed"] == 1
    assert 0 <= data["pass_rate"] <= 1
    assert 0 <= data["success_rate"] <= 1
    assert 0 <= data["consistency_rate"] <= 1
    assert data["hard_fail_count"] == 1
    assert data["failure_variance"] >= 0
    assert "median_score" in data
    assert "worst_task_score" in data
    assert "work_product_compatibility_rate" in data


def test_secret_like_output_is_detected() -> None:
    assert _contains_secret_like_value("OR-01") is False
    assert _contains_secret_like_value("sk-or-v1-example") is True
    assert _contains_secret_like_value("Authorization: Bearer secret") is True


def test_prepare_workspace_initializes_git_before_git_safety_validation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.txt").write_text("benchmark\n", encoding="utf-8")

    temp, _ = _prepare_workspace(source)
    try:
        assert (temp / ".git").is_dir()
    finally:
        import shutil
        shutil.rmtree(temp, ignore_errors=True)
