from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from execution_gate import FileChange
from git_mutation_executor import GitMutationExecutor, GitMutationVerificationError
from process_sandbox import ProcessSandbox
from sandbox_policy import WorkspaceResourcePolicy


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [shutil.which("git") or "git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
        shell=False,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> tuple[Path, GitMutationExecutor]:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    run_git(workspace, "init")
    run_git(workspace, "config", "user.name", "Agent Test")
    run_git(workspace, "config", "user.email", "agent-test@example.invalid")
    (workspace / "calculator.py").write_text("VALUE = 1\n", encoding="utf-8")
    run_git(workspace, "add", "--", "calculator.py")
    run_git(workspace, "commit", "-m", "baseline")

    git_executable = Path(shutil.which("git") or "git").resolve()
    sandbox = ProcessSandbox(
        WorkspaceResourcePolicy(
            workspace,
            allowed_tool_paths=[git_executable],
        ),
        timeout_seconds=5,
    )
    return workspace, GitMutationExecutor(workspace, process_sandbox=sandbox)


def blob_oid(text: str) -> str:
    payload = text.encode("utf-8")
    return hashlib.sha1(f"blob {len(payload)}\0".encode("ascii") + payload).hexdigest()


def test_staged_index_content_must_match_validated_filechange(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    actual_staged = "VALUE = 2\n"
    validated = FileChange(
        path="calculator.py",
        old_text="VALUE = 1\n",
        new_text="VALUE = 3\n",
    )
    (workspace / "calculator.py").write_text(actual_staged, encoding="utf-8")
    run_git(workspace, "add", "--", "calculator.py")

    with pytest.raises(
        GitMutationVerificationError,
        match="Staged object ID mismatch",
    ):
        executor._verify_staged_contents([validated], ["calculator.py"])

    staged = run_git(
        workspace,
        "ls-files",
        "--stage",
        "--",
        "calculator.py",
    ).stdout.strip().split()
    assert staged[1] == blob_oid(actual_staged)


def test_staged_index_content_matches_validated_filechange(
    repo: tuple[Path, GitMutationExecutor],
) -> None:
    workspace, executor = repo
    validated = FileChange(
        path="calculator.py",
        old_text="VALUE = 1\n",
        new_text="VALUE = 2\n",
    )
    (workspace / "calculator.py").write_text(validated.new_text, encoding="utf-8")
    run_git(workspace, "add", "--", "calculator.py")

    executor._verify_staged_contents([validated], ["calculator.py"])


def test_parse_status_preserves_literal_arrow_and_space_in_filename() -> None:
    raw = " M file -> draft.py\0"
    records = GitMutationExecutor._parse_status_records(raw)

    assert records == [(" ", "M", ("file -> draft.py",))]


def test_parse_status_decodes_unusual_utf8_filename_without_git_quoting() -> None:
    raw = "?? café notes.txt\0"
    records = GitMutationExecutor._parse_status_records(raw)

    assert records == [("?", "?", ("café notes.txt",))]
