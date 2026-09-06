from __future__ import annotations

from collections.abc import Iterable, Sequence


class GitCommitEvidenceError(RuntimeError):
    """Raised when committed-target evidence cannot be trusted."""


def normalize_path(value: str) -> str:
    """Normalize Git path separators without reparsing pathname content."""
    normalized = value.replace("\\", "/")
    if not normalized:
        raise GitCommitEvidenceError("Git commit evidence contained an empty pathname")
    return normalized


def parse_nul_path_records(output: str) -> tuple[str, ...]:
    """Parse NUL-delimited Git pathname evidence conservatively.

    The caller must provide the stdout from a Git command using a NUL-delimited
    pathname format such as ``--name-only -z``. Newlines and other separators in
    filenames are treated as ordinary pathname bytes and are never interpreted
    as record boundaries.
    """

    if not isinstance(output, str):
        raise GitCommitEvidenceError("Git commit evidence must be text output")

    if "\x00" not in output:
        if output:
            raise GitCommitEvidenceError(
                "Git commit pathname evidence is not NUL-delimited"
            )
        return ()

    raw_records = output.split("\x00")
    if raw_records[-1] != "":
        raise GitCommitEvidenceError(
            "Git commit pathname evidence is not terminated by NUL"
        )

    records = []
    for raw in raw_records[:-1]:
        if not raw:
            raise GitCommitEvidenceError(
                "Git commit pathname evidence contained an empty record"
            )
        records.append(normalize_path(raw))
    return tuple(records)


def verify_exact_target_set(
    output: str,
    targets: Sequence[str] | Iterable[str],
) -> tuple[str, ...]:
    """Require committed pathname evidence to match the authorized target set."""

    actual = parse_nul_path_records(output)
    expected = tuple(normalize_path(str(target)) for target in targets)

    if len(actual) != len(set(actual)):
        raise GitCommitEvidenceError(
            "Git commit pathname evidence contained duplicate records"
        )

    if len(expected) != len(set(expected)):
        raise GitCommitEvidenceError(
            "Authorized Git target set contained duplicate paths"
        )

    if set(actual) != set(expected) or len(actual) != len(expected):
        raise GitCommitEvidenceError(
            f"Committed target set mismatch: expected={sorted(expected)!r} actual={sorted(actual)!r}"
        )

    return tuple(sorted(actual))
