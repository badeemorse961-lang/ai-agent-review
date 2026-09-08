from __future__ import annotations

from pathlib import Path

from model_benchmark import Candidate, ToolTrace, _hard_failures, _prepare_workspace, load_corpus


def test_secret_leakage_is_a_hard_failure() -> None:
    task = next(item for item in load_corpus()["tasks"] if item["id"] == "L1")
    hard = _hard_failures(
        task,
        {"objective": "Bearer sk-or-v1-secret"},
        [],
        ToolTrace(False, 0, None, True, True, True),
        True,
        True,
        set(),
    )
    assert "secret_leakage" in hard


def test_prepare_workspace_excludes_git_and_local_results(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "tracked.txt").write_text("tracked", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("config", encoding="utf-8")
    (tmp_path / "benchmark_results.local.json").write_text("local", encoding="utf-8")
    calls: list[tuple[str, ...]] = []

    class FakeResult:
        returncode = 0
        timed_out = False

    class FakeExecutor:
        def run(self, command, **kwargs):
            calls.append(tuple(command))
            return FakeResult()

    monkeypatch.setattr("model_benchmark._executor", lambda root: FakeExecutor())
    disposable, _ = _prepare_workspace(tmp_path)
    try:
        assert disposable != tmp_path
        assert (disposable / "tracked.txt").read_text(encoding="utf-8") == "tracked"
        assert not (disposable / ".git").exists()
        assert not (disposable / "benchmark_results.local.json").exists()
        assert calls == [("git", "init"), ("git", "add", "-A")]
    finally:
        import shutil
        shutil.rmtree(disposable, ignore_errors=True)


def test_benchmark_candidate_identity_is_not_a_model_decision() -> None:
    candidate = Candidate("openrouter", "openai/gpt-5.6-luna", "OR-01")
    assert candidate.model == "openai/gpt-5.6-luna"
    assert candidate.connection_id == "OR-01"
