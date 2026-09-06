from __future__ import annotations

import pytest

from git_staged_evidence import (
    GitStagedEvidenceError,
    parse_nul_index_records,
    verify_exact_staged_targets,
)


def test_parse_nul_index_records_preserves_complex_pathnames() -> None:
    output = (
        "100644 abcdef0123456789abcdef0123456789abcdef01 0\tsrc/file with spaces.py\0"
        "100644 0123456789abcdef0123456789abcdef01234567 0\tsrc/line\nname.py\0"
    )
    entries = parse_nul_index_records(output, object_format="sha1")
    assert [entry.path for entry in entries] == ["src/file with spaces.py", "src/line\nname.py"]
    assert all(entry.stage == 0 for entry in entries)


def test_parse_rejects_line_oriented_output() -> None:
    with pytest.raises(GitStagedEvidenceError, match="not NUL-delimited"):
        parse_nul_index_records(
            "100644 abcdef0123456789abcdef0123456789abcdef01 0\tfile.py\n",
            object_format="sha1",
        )


def test_parse_rejects_unterminated_output() -> None:
    with pytest.raises(GitStagedEvidenceError, match="not terminated"):
        parse_nul_index_records(
            "100644 abcdef0123456789abcdef0123456789abcdef01 0\tfile.py",
            object_format="sha1",
        )


def test_parse_rejects_empty_record() -> None:
    with pytest.raises(GitStagedEvidenceError, match="empty record"):
        parse_nul_index_records(
            "100644 abcdef0123456789abcdef0123456789abcdef01 0\tfile.py\0\0",
            object_format="sha1",
        )


def test_parse_rejects_invalid_object_id_length() -> None:
    with pytest.raises(GitStagedEvidenceError, match="invalid object ID"):
        parse_nul_index_records(
            "100644 abcdef 0\tfile.py\0",
            object_format="sha1",
        )


def test_verify_exact_staged_targets_and_objects() -> None:
    output = "100644 abcdef0123456789abcdef0123456789abcdef01 0\tfile.py\0"
    entries = verify_exact_staged_targets(
        output,
        ("file.py",),
        object_format="sha1",
        expected_object_ids={"file.py": "abcdef0123456789abcdef0123456789abcdef01"},
    )
    assert entries[0].path == "file.py"


def test_verify_rejects_duplicate_evidence() -> None:
    record = "100644 abcdef0123456789abcdef0123456789abcdef01 0\tfile.py\0"
    with pytest.raises(GitStagedEvidenceError, match="duplicate paths"):
        verify_exact_staged_targets(
            record + record,
            ("file.py",),
            object_format="sha1",
        )


def test_verify_rejects_nonzero_stage() -> None:
    output = "100644 abcdef0123456789abcdef0123456789abcdef01 2\tfile.py\0"
    with pytest.raises(GitStagedEvidenceError, match="non-zero"):
        verify_exact_staged_targets(
            output,
            ("file.py",),
            object_format="sha1",
        )


def test_verify_rejects_object_id_mismatch() -> None:
    output = "100644 abcdef0123456789abcdef0123456789abcdef01 0\tfile.py\0"
    with pytest.raises(GitStagedEvidenceError, match="object ID mismatch"):
        verify_exact_staged_targets(
            output,
            ("file.py",),
            object_format="sha1",
            expected_object_ids={"file.py": "0123456789abcdef0123456789abcdef01234567"},
        )
