from __future__ import annotations

from pathlib import Path

import pytest

from git_commit_evidence import (
    GitCommitEvidenceError,
    normalize_path,
    parse_nul_path_records,
    verify_exact_target_set,
)


def test_parse_nul_records_preserves_complex_filenames() -> None:
    output = (
        "src/file with spaces.py\0"
        "src/arrow -> literal.txt\0"
        "src/quote\"name.py\0"
        "src/unicode-→.txt\0"
        "src/line\nname.md\0"
    )

    assert parse_nul_path_records(output) == (
        "src/file with spaces.py",
        "src/arrow -> literal.txt",
        'src/quote"name.py',
        "src/unicode-→.txt",
        "src/line\nname.md",
    )


def test_parse_nul_records_rejects_non_nul_output() -> None:
    with pytest.raises(GitCommitEvidenceError):
        parse_nul_path_records("calculator.py\nREADME.md\n")


def test_parse_nul_records_rejects_unterminated_output() -> None:
    with pytest.raises(GitCommitEvidenceError):
        parse_nul_path_records("calculator.py\0README.md")


def test_parse_nul_records_rejects_empty_record() -> None:
    with pytest.raises(GitCommitEvidenceError):
        parse_nul_path_records("calculator.py\0\0")


def test_exact_target_set_requires_identical_paths() -> None:
    output = "calculator.py\0README.md\0"

    assert verify_exact_target_set(output, ("README.md", "calculator.py")) == (
        "README.md",
        "calculator.py",
    )


def test_exact_target_set_rejects_unrelated_committed_path() -> None:
    with pytest.raises(GitCommitEvidenceError):
        verify_exact_target_set(
            "calculator.py\0unrelated.py\0",
            ("calculator.py",),
        )


def test_exact_target_set_rejects_duplicate_evidence() -> None:
    with pytest.raises(GitCommitEvidenceError):
        verify_exact_target_set(
            "calculator.py\0calculator.py\0",
            ("calculator.py",),
        )


def test_exact_target_set_rejects_duplicate_authorization() -> None:
    with pytest.raises(GitCommitEvidenceError):
        verify_exact_target_set(
            "calculator.py\0",
            ("calculator.py", "calculator.py"),
        )


def test_exact_target_set_normalizes_windows_separators() -> None:
    output = "src\\nested\\calculator.py\0"

    assert verify_exact_target_set(output, ("src/nested/calculator.py",)) == (
        "src/nested/calculator.py",
    )


def test_normalize_path_rejects_empty_path() -> None:
    with pytest.raises(GitCommitEvidenceError):
        normalize_path("")
