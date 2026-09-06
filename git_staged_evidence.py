from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import re


class GitStagedEvidenceError(RuntimeError):
    """Raised when staged-index pathname or object evidence cannot be trusted."""


_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


@dataclass(frozen=True)
class StagedIndexEntry:
    mode: str
    object_id: str
    stage: int
    path: str


def normalize_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if not normalized:
        raise GitStagedEvidenceError("Git staged-index evidence contained an empty pathname")
    return normalized


def parse_nul_index_records(output: str, *, object_format: str) -> tuple[StagedIndexEntry, ...]:
    """Parse ``git ls-files --stage -z`` output without line-oriented pathname parsing."""
    if not isinstance(output, str):
        raise GitStagedEvidenceError("Git staged-index evidence must be text output")
    if object_format not in {"sha1", "sha256"}:
        raise GitStagedEvidenceError("Unsupported Git object format")
    expected_oid_length = 40 if object_format == "sha1" else 64

    if not output:
        return ()
    if "\x00" not in output:
        raise GitStagedEvidenceError("Git staged-index evidence is not NUL-delimited")
    if not output.endswith("\x00"):
        raise GitStagedEvidenceError("Git staged-index evidence is not terminated by NUL")

    raw_records = output[:-1].split("\x00")
    if any(not raw for raw in raw_records):
        raise GitStagedEvidenceError("Git staged-index evidence contained an empty record")

    entries: list[StagedIndexEntry] = []
    for raw in raw_records:
        if "\t" not in raw:
            raise GitStagedEvidenceError("Git staged-index record is missing its pathname separator")

        header, raw_path = raw.split("\t", 1)
        fields = header.split(" ")
        if len(fields) != 3 or any(not field for field in fields):
            raise GitStagedEvidenceError("Git staged-index record has an invalid header")
        mode, object_id, stage_text = fields
        if len(mode) != 6 or not mode.isdigit():
            raise GitStagedEvidenceError("Git staged-index record has an invalid mode")
        if not _HEX_RE.fullmatch(object_id) or len(object_id) != expected_oid_length:
            raise GitStagedEvidenceError("Git staged-index record has an invalid object ID")
        if stage_text not in {"0", "1", "2", "3"}:
            raise GitStagedEvidenceError("Git staged-index record has an invalid stage")
        path = normalize_path(raw_path)
        entries.append(
            StagedIndexEntry(
                mode=mode,
                object_id=object_id.lower(),
                stage=int(stage_text),
                path=path,
            )
        )

    return tuple(entries)


def verify_exact_staged_targets(
    output: str,
    targets: Sequence[str] | Iterable[str],
    *,
    object_format: str,
    expected_object_ids: dict[str, str] | None = None,
) -> tuple[StagedIndexEntry, ...]:
    entries = parse_nul_index_records(output, object_format=object_format)
    normalized_targets = tuple(normalize_path(str(target)) for target in targets)

    if len(normalized_targets) != len(set(normalized_targets)):
        raise GitStagedEvidenceError("Authorized staged target set contained duplicate paths")
    if len(entries) != len({entry.path for entry in entries}):
        raise GitStagedEvidenceError("Git staged-index evidence contained duplicate paths")
    if any(entry.stage != 0 for entry in entries):
        raise GitStagedEvidenceError("Git staged-index evidence contained a non-zero merge stage")

    actual_paths = {entry.path for entry in entries}
    expected_paths = set(normalized_targets)
    if actual_paths != expected_paths or len(entries) != len(normalized_targets):
        raise GitStagedEvidenceError(
            f"Staged target set mismatch: expected={sorted(expected_paths)!r} actual={sorted(actual_paths)!r}"
        )

    if expected_object_ids is not None:
        normalized_expected = {
            normalize_path(str(path)): str(object_id).lower()
            for path, object_id in expected_object_ids.items()
        }
        if set(normalized_expected) != expected_paths:
            raise GitStagedEvidenceError("Expected staged object-ID mapping does not match target set")
        for entry in entries:
            expected = normalized_expected[entry.path]
            if entry.object_id != expected:
                raise GitStagedEvidenceError(
                    f"Staged object ID mismatch for {entry.path!r}: expected={expected!r} actual={entry.object_id!r}"
                )

    return tuple(sorted(entries, key=lambda entry: entry.path))
