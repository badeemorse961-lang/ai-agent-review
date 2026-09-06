from __future__ import annotations

import os
import sys
from pathlib import Path

from execution_gate import ExecutionGate
from process_sandbox import ProcessSandbox
from sandbox_policy import WorkspaceResourcePolicy


def test_process_sandbox_redacts_explicit_environment_secret(tmp_path: Path) -> None:
    script = tmp_path / "emit_secret.py"
    script.write_text(
        "import os\n"
        "print(os.environ['AGENT_SECRET'])\n"
        "print('Authorization: Bearer ' + os.environ['AGENT_SECRET'])\n"
        "print('api_key=' + os.environ['AGENT_SECRET'])\n",
        encoding="utf-8",
    )

    policy = WorkspaceResourcePolicy(
        tmp_path,
        allowed_tool_paths=[Path(sys.executable)],
    )
    sandbox = ProcessSandbox(policy)
    secret = "custom-secret-value-987654"

    result = sandbox.run(
        [sys.executable, str(script)],
        env={"AGENT_SECRET": secret},
    )

    assert result.returncode == 0
    assert secret not in result.stdout
    assert "[REDACTED]" in result.stdout
    assert "Bearer [REDACTED]" in result.stdout
    assert "api_key=[REDACTED]" in result.stdout


def test_execution_gate_redacts_failing_pytest_output_and_state(tmp_path: Path, monkeypatch) -> None:
    secret = "gate-custom-secret-value-123456"
    monkeypatch.setenv("AGENT_SECRET", secret)

    (tmp_path / "test_leak.py").write_text(
        "import os\n"
        "\n"
        "def test_failure():\n"
        "    print(os.environ['AGENT_SECRET'])\n"
        "    assert False\n",
        encoding="utf-8",
    )

    gate = ExecutionGate(tmp_path)
    result = gate.run_tests()

    assert result.passed is False
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert secret not in str(gate.state["last_test"])
    assert "[REDACTED]" in (result.stdout + result.stderr)


def test_standard_process_environment_does_not_expose_secret_like_variables(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "gsk_hidden-but-not-passed")
    monkeypatch.setenv("OPENROUTER_TOKEN", "sk-or-v1-hidden-but-not-passed")

    policy = WorkspaceResourcePolicy(
        tmp_path,
        allowed_tool_paths=[Path(sys.executable)],
    )
    sandbox = ProcessSandbox(policy)

    script = tmp_path / "dump_env.py"
    script.write_text(
        "import os\n"
        "print('GROQ=' + str(os.getenv('GROQ_API_KEY')))\n"
        "print('OPENROUTER=' + str(os.getenv('OPENROUTER_TOKEN')))\n",
        encoding="utf-8",
    )

    result = sandbox.run([sys.executable, str(script)])

    assert result.returncode == 0
    assert "gsk_hidden-but-not-passed" not in result.stdout
    assert "sk-or-v1-hidden-but-not-passed" not in result.stdout
