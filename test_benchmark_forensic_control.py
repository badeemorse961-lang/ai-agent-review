from __future__ import annotations

import json
import shutil
from pathlib import Path

import benchmark_forensic
import model_benchmark as benchmark


CONTROL_TASK = {
    "id": "CONTROL-CODE-PASS",
    "class": "SIMPLE",
    "kind": "code",
    "prompt": "Apply the supplied deterministic control fixture patch and validate it.",
    "expected": {
        "required_fields": {
            "summary": "string",
            "rationale": "string",
            "touched_paths": "list",
            "unified_diff": "string",
        },
        "changed_paths_exact": ["control_fixture.py"],
        "required_file_contains": {
            "control_fixture.py": [
                "def test_control_regression",
                "assert \"ok\" == \"ok\"",
            ]
        },
        "forbidden_file_contains": {},
        "require_work_product": False,
        "required_behavior": "The deterministic control patch adds one passing regression test and changes no other file.",
    },
    "verification": ["python -m pytest -q control_fixture.py"],
    "target_paths": ["control_fixture.py"],
}

GOLDEN_CONTENT = """--- a/control_fixture.py\n+++ b/control_fixture.py\n@@ -1,2 +1,5 @@\n def test_control_fixture():\n     assert 2 + 2 == 4\n+\n+def test_control_regression():\n+    assert \"ok\" == \"ok\"\n"""

GOLDEN_RESPONSE = {
    "choices": [
        {
            "message": {
                "content": json.dumps(
                    {
                        "summary": "Added the deterministic passing control regression test.",
                        "rationale": "The fixture changes one approved test file only and the resulting test remains green.",
                        "touched_paths": ["control_fixture.py"],
                        "unified_diff": GOLDEN_CONTENT,
                    }
                )
            }
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 8, "cost": 0.0},
}


def _make_workspace(root: Path) -> tuple[Path, benchmark.TerminalExecutor]:
    workspace = root / "workspace"
    workspace.mkdir()
    (workspace / "control_fixture.py").write_text(
        "def test_control_fixture():\n    assert 2 + 2 == 4\n", encoding="utf-8"
    )
    return workspace, benchmark._executor(workspace)


def test_control_fixture_proves_full_pass_path(monkeypatch, tmp_path) -> None:
    candidate = benchmark.Candidate("fixture", "golden-control", "CONTROL")

    monkeypatch.setattr(benchmark, "_prepare_workspace", lambda _root: _make_workspace(tmp_path))
    monkeypatch.setattr(benchmark, "read_context", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        benchmark,
        "call_model",
        lambda *_args, **_kwargs: (
            GOLDEN_RESPONSE,
            12.0,
            benchmark.ToolTrace(False, 0, None, True, True, True, False),
            (10, 8, 0.0),
        ),
    )
    monkeypatch.setattr(benchmark, "WindowsProtectedSecretStore", lambda: object())

    result = benchmark_forensic.collect_task(tmp_path, CONTROL_TASK, candidate)
    pytest_executable = shutil.which("pytest")
    assert pytest_executable is not None

    artifact = tmp_path / "control_forensic_artifact.json"
    artifact.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    persisted = json.loads(artifact.read_text(encoding="utf-8"))

    assert persisted["model_response_received"] is True
    assert persisted["structured_ok"] is True
    assert persisted["work_product_ok"] is True
    assert persisted["changed_paths"] == ["control_fixture.py"]
    assert persisted["semantic_pass"] is True
    assert persisted["semantic_failures"] == []
    assert persisted["hard_failures"] == []
    assert persisted["regression_ok"] is True
    assert persisted["verification"]["executed"] is True
    assert persisted["verification"]["normalized_command"] == [pytest_executable, "-q", "control_fixture.py"]
    assert persisted["verification"]["terminal_executor_executable"] == pytest_executable
    assert persisted["verification"]["returncode"] == 0
    assert persisted["verification"]["timed_out"] is False
    assert "2 passed" in persisted["verification"]["stdout"]
    assert persisted["forensic_status"] == "COMPLETE"
    artifact_text = artifact.read_text(encoding="utf-8")
    assert "sk-or-v1-" not in artifact_text
    assert "gsk_" not in artifact_text
    assert "Authorization: Bearer" not in artifact_text
    assert "[REDACTED]" not in artifact_text


def test_control_fixture_proves_existing_scoring_path_without_inference(tmp_path) -> None:
    workspace, executor = _make_workspace(tmp_path)
    try:
        score, dimensions, structured_ok, tool_ok, regression_ok, work_product_ok, semantic_pass, hard_failures, error = benchmark.evaluate(
            CONTROL_TASK,
            GOLDEN_RESPONSE,
            12.0,
            executor,
            workspace,
            benchmark.ToolTrace(False, 0, None, True, True, True, False),
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    assert score > 0
    assert dimensions["correctness"] == 30.0
    assert structured_ok is True
    assert tool_ok is True
    assert regression_ok is True
    assert work_product_ok is True
    assert semantic_pass is True
    assert hard_failures == []
    assert error is None
