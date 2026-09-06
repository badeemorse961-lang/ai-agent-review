from __future__ import annotations

from pathlib import Path

import pytest

import execution_gate
from execution_gate_process_runner import ExecutionGateProcessRunner
from process_sandbox import ProcessResult, ProcessSandboxSafetyStop


def test_process_runner_uses_absolute_allowlisted_pytest(tmp_path: Path) -> None:
    runner = ExecutionGateProcessRunner(
        tmp_path,
        timeout_seconds=5,
        max_output_chars=4096,
    )

    assert runner.pytest_executable.is_absolute()
    assert runner.pytest_executable.is_file()
    assert runner.pytest_executable in runner.sandbox.policy.allowed_tool_paths


def test_process_runner_executes_pytest_inside_workspace(tmp_path: Path) -> None:
    (tmp_path / "test_nested.py").write_text(
        "def test_nested():\n    assert 2 + 3 == 5\n",
        encoding="utf-8",
    )

    runner = ExecutionGateProcessRunner(
        tmp_path,
        timeout_seconds=10,
        max_output_chars=8192,
    )
    result = runner.run(("-q",))

    assert result.returncode == 0
    assert result.timed_out is False
    assert result.isolated_process_group is True
    assert "passed" in result.stdout


def test_process_runner_fails_closed_when_pytest_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("execution_gate_process_runner.shutil.which", lambda _: None)

    with pytest.raises(ProcessSandboxSafetyStop):
        ExecutionGateProcessRunner(
            tmp_path,
            timeout_seconds=5,
        )


def test_execution_gate_run_tests_delegates_to_process_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = execution_gate.ExecutionGate(tmp_path)
    calls: list[tuple[str, ...]] = []

    def fake_run(self: ExecutionGateProcessRunner, args: tuple[str, ...]) -> ProcessResult:
        calls.append(args)
        return ProcessResult(
            returncode=0,
            stdout="1 passed",
            stderr="",
            timed_out=False,
            truncated=False,
            isolated_process_group=True,
            containment_mode="workspace_guarded",
        )

    monkeypatch.setattr(ExecutionGateProcessRunner, "run", fake_run)
    result = gate.run_tests()

    assert result.passed is True
    assert result.return_code == 0
    assert calls == [("-q",)]
    assert result.command == ["pytest", "-q"]
    assert gate.state["state"] == "TESTING"


def test_execution_gate_treats_process_timeout_as_test_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = execution_gate.ExecutionGate(tmp_path)

    def fake_run(self: ExecutionGateProcessRunner, args: tuple[str, ...]) -> ProcessResult:
        return ProcessResult(
            returncode=-1,
            stdout="partial output",
            stderr="sandbox timeout",
            timed_out=True,
            truncated=False,
            isolated_process_group=True,
            containment_mode="workspace_guarded",
        )

    monkeypatch.setattr(ExecutionGateProcessRunner, "run", fake_run)
    result = gate.run_tests()

    assert result.passed is False
    assert result.return_code == -1
    assert "TEST TIMEOUT" in result.stderr
    assert result.command == ["pytest", "-q"]
