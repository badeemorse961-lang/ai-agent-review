from pathlib import Path
from types import SimpleNamespace

import pytest

from model_benchmark import _executor, _run_verification
from process_sandbox import ProcessSandboxSafetyStop


class _FakeExecutor:
    def __init__(self) -> None:
        self.commands: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def run(self, command, *, target_paths=()):
        self.commands.append((tuple(command), tuple(target_paths)))
        return SimpleNamespace(returncode=0, timed_out=False)


def test_run_verification_accepts_python_module_pytest() -> None:
    executor = _FakeExecutor()
    task = {
        "verification": ["python -m pytest -q test_calculator.py"],
        "target_paths": ["test_calculator.py"],
    }

    assert _run_verification(executor, task) is True
    assert executor.commands == [
        (("pytest", "-q", "test_calculator.py"), ("test_calculator.py",))
    ]


def test_run_verification_rejects_python_module_other_than_pytest() -> None:
    executor = _FakeExecutor()
    task = {
        "verification": ["python -m unittest test_calculator.py"],
        "target_paths": ["test_calculator.py"],
    }

    assert _run_verification(executor, task) is False
    assert executor.commands == []


def test_run_verification_rejects_unapproved_executable() -> None:
    executor = _FakeExecutor()
    task = {
        "verification": ["powershell -File verify.ps1"],
        "target_paths": ["test_calculator.py"],
    }

    assert _run_verification(executor, task) is False
    assert executor.commands == []


def test_run_verification_preserves_workspace_path_safety(tmp_path: Path) -> None:
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    executor = _executor(tmp_path)
    task = {
        "verification": ["python -m pytest -q ../outside_test.py"],
        "target_paths": ["test_ok.py"],
    }

    with pytest.raises(ProcessSandboxSafetyStop):
        _run_verification(executor, task)
