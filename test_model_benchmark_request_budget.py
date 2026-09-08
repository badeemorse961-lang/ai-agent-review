from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from model_benchmark import MAX_BENCHMARK_TOKENS, Candidate, _tool_loop, call_model


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_normal_request_payload_sets_explicit_8192_max_tokens() -> None:
    assert MAX_BENCHMARK_TOKENS == 8192
    captured: list[dict] = []

    def fake_post(*args, **kwargs):
        captured.append(kwargs["json"])
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps({"classification": "ANALYZE_PLAN"}),
                        }
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            }
        )

    candidate = Candidate("openrouter", "openai/gpt-5.6-luna", "OR-01")
    task = {"class": "SIMPLE", "kind": "structured", "prompt": "return a bounded JSON result"}
    store = SimpleNamespace(get=lambda *_: "protected-secret")

    with patch("model_benchmark.requests.post", side_effect=fake_post):
        call_model(candidate, task, "context", store, Path("."))

    assert len(captured) == 1
    assert captured[0]["max_tokens"] == 8192


def test_tool_loop_request_payloads_set_explicit_8192_max_tokens(tmp_path: Path) -> None:
    (tmp_path / "PROJECT_RULES.md").write_text("benchmark context\n", encoding="utf-8")
    task = {
        "class": "SIMPLE",
        "kind": "tool",
        "prompt": "read the approved context file and return a JSON plan",
        "context_files": ["PROJECT_RULES.md"],
        "expected": {
            "allowed_tools": ["read_context_file"],
        },
    }
    candidate = Candidate("openrouter", "openai/gpt-5.6-luna", "OR-01")
    first_payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "read_context_file",
                                "arguments": '{"path":"PROJECT_RULES.md"}',
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    }
    second_payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"classification": "PLAN", "plan": ["use approved evidence"]}),
                }
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 4},
    }
    captured: list[dict] = []

    def fake_post(*args, **kwargs):
        captured.append(kwargs["json"])
        return _FakeResponse(first_payload if len(captured) == 1 else second_payload)

    store = SimpleNamespace(get=lambda *_: "protected-secret")
    with patch("model_benchmark.requests.post", side_effect=fake_post):
        _tool_loop(candidate, task, "context", store, tmp_path)

    assert len(captured) == 2
    assert all(payload["max_tokens"] == 8192 for payload in captured)
