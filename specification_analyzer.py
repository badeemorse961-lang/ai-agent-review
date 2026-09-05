from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional


SCHEMA_VERSION = 1

DEFAULT_DOCUMENT_NAMES = {
    "task.md",
    "requirements.md",
    "requirement.md",
    "specification.md",
    "spec.md",
    "project_spec.md",
    "design.md",
    "architecture.md",
    "rules.md",
    "project_rules.md",
    "roadmap.md",
}

MARKDOWN_EXTENSIONS = {".md", ".markdown", ".rst", ".txt"}
EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
    "build",
    "dist",
    "coverage",
}

REQUIREMENT_MARKERS = (
    "must",
    "should",
    "shall",
    "required",
    "requires",
    "need to",
    "do not",
    "must not",
    "should not",
    "يجب",
    "يلزم",
    "يتعين",
    "مطلوب",
    "لا تعيد",
    "لا تقم",
    "يمنع",
)

SECTION_HINTS = (
    "requirement",
    "requirements",
    "specification",
    "spec",
    "المتطلبات",
    "المهمة",
    "requirements",
)


@dataclass(frozen=True)
class Requirement:
    requirement_id: str
    source: str
    line: int
    text: str
    kind: str
    strength: str


@dataclass(frozen=True)
class SpecificationDocument:
    path: str
    requirement_count: int


class SpecificationAnalyzer:
    """Deterministically extract explicit requirements from local documents.

    This component observes text only. It never executes project code, calls a
    provider, or treats extracted prose as proof of implementation.
    """

    def __init__(
        self,
        workspace_root: Path,
        max_document_bytes: int = 200_000,
        max_requirements: int = 1_000,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.max_document_bytes = max_document_bytes
        self.max_requirements = max_requirements

        if not self.workspace_root.exists():
            raise ValueError(f"Workspace does not exist: {self.workspace_root}")
        if not self.workspace_root.is_dir():
            raise ValueError(f"Workspace is not a directory: {self.workspace_root}")

    def discover_documents(self, candidate_paths: Optional[Iterable[str]] = None) -> List[Path]:
        if candidate_paths is not None:
            paths = []
            for raw in candidate_paths:
                path = (self.workspace_root / raw).resolve()
                self._ensure_inside_workspace(path)
                if path.is_file():
                    paths.append(path)
            return sorted(set(paths), key=lambda value: value.as_posix().lower())

        discovered: List[Path] = []
        for path in self.workspace_root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in EXCLUDED_DIRS or part.startswith(".agent_") for part in path.relative_to(self.workspace_root).parts[:-1]):
                continue
            if path.suffix.lower() not in MARKDOWN_EXTENSIONS:
                continue

            relative_name = path.name.lower()
            relative_path = "/" + path.relative_to(self.workspace_root).as_posix().lower() + "/"
            is_named_document = relative_name in DEFAULT_DOCUMENT_NAMES
            is_document_directory = any(
                f"/{fragment}/" in relative_path
                for fragment in ("docs", "doc", "spec", "specs", "requirements", "design")
            )
            if is_named_document or is_document_directory:
                discovered.append(path)

        return sorted(set(discovered), key=lambda value: value.as_posix().lower())

    def analyze(self, candidate_paths: Optional[Iterable[str]] = None) -> dict[str, Any]:
        requirements: List[Requirement] = []
        documents: List[SpecificationDocument] = []

        for path in self.discover_documents(candidate_paths):
            extracted = self._extract_requirements(path)
            relative = path.relative_to(self.workspace_root).as_posix()
            documents.append(
                SpecificationDocument(
                    path=relative,
                    requirement_count=len(extracted),
                )
            )
            requirements.extend(extracted)

            if len(requirements) >= self.max_requirements:
                raise ValueError(
                    f"Specification exceeds maximum requirement count ({self.max_requirements})."
                )

        requirements = self._deduplicate(requirements)
        conflicts = self._detect_exact_conflicts(requirements)

        return {
            "schema_version": SCHEMA_VERSION,
            "analyzer": {
                "name": "SpecificationAnalyzer",
                "version": "v1",
            },
            "workspace": {
                "root": str(self.workspace_root),
            },
            "documents": [asdict(item) for item in documents],
            "requirements": [asdict(item) for item in requirements],
            "unresolved_conflicts": conflicts,
            "requirement_count": len(requirements),
        }

    def _extract_requirements(self, path: Path) -> List[Requirement]:
        try:
            if path.stat().st_size > self.max_document_bytes:
                return []
            text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            return []

        requirements: List[Requirement] = []
        in_requirement_section = False

        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("#"):
                heading = line.lstrip("#").strip().lower()
                in_requirement_section = any(
                    hint in heading for hint in SECTION_HINTS
                )
                continue

            candidate = self._clean_candidate(line)
            if not candidate:
                continue

            normalized = candidate.casefold()
            marked = any(marker in normalized for marker in REQUIREMENT_MARKERS)
            bullet_like = bool(re.match(r"^(?:[-*+]\s+|\d+[.)]\s+)", candidate))

            if not (marked or (in_requirement_section and bullet_like)):
                continue

            kind = "constraint" if any(
                marker in normalized
                for marker in ("do not", "must not", "should not", "لا ", "يمنع")
            ) else "behavior"
            strength = "mandatory" if any(
                marker in normalized
                for marker in ("must", "shall", "required", "يجب", "يلزم", "يتعين", "مطلوب", "لا ", "يمنع")
            ) else "advisory"

            requirement_id = self._make_id(path, line_number, candidate)
            requirements.append(
                Requirement(
                    requirement_id=requirement_id,
                    source=path.relative_to(self.workspace_root).as_posix(),
                    line=line_number,
                    text=candidate,
                    kind=kind,
                    strength=strength,
                )
            )

        return requirements

    @staticmethod
    def _clean_candidate(line: str) -> str:
        candidate = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line).strip()
        candidate = re.sub(r"^>\s*", "", candidate).strip()
        return candidate

    @staticmethod
    def _make_id(path: Path, line_number: int, text: str) -> str:
        payload = f"{path.as_posix()}:{line_number}:{text}".encode("utf-8")
        return "REQ-" + hashlib.sha256(payload).hexdigest()[:12]

    @staticmethod
    def _deduplicate(requirements: List[Requirement]) -> List[Requirement]:
        seen: set[str] = set()
        result: List[Requirement] = []
        for requirement in requirements:
            if requirement.requirement_id in seen:
                continue
            seen.add(requirement.requirement_id)
            result.append(requirement)
        return result

    @classmethod
    def _detect_exact_conflicts(cls, requirements: List[Requirement]) -> List[dict[str, Any]]:
        """Detect only explicit same-subject positive/negative text pairs.

        The detector is intentionally conservative. Ambiguous natural-language
        contradictions are left unresolved for higher-level analysis.
        """
        conflicts: List[dict[str, Any]] = []
        normalized: list[tuple[Requirement, str]] = [
            (req, req.text.casefold()) for req in requirements
        ]

        for index, (left, left_text) in enumerate(normalized):
            for right, right_text in normalized[index + 1 :]:
                if left.source != right.source:
                    continue
                left_base = cls._conflict_base(left_text)
                right_base = cls._conflict_base(right_text)
                if not left_base or left_base != right_base:
                    continue
                if cls._is_negative(left_text) != cls._is_negative(right_text):
                    conflicts.append(
                        {
                            "left_requirement_id": left.requirement_id,
                            "right_requirement_id": right.requirement_id,
                            "source": left.source,
                            "reason": "Explicit positive/negative requirement pair.",
                        }
                    )

        return conflicts

    @staticmethod
    def _is_negative(text: str) -> bool:
        negative_markers = ("do not", "must not", "should not", "لا ", "لا ", "يمنع")
        return any(marker in text for marker in negative_markers)

    @classmethod
    def _conflict_base(cls, text: str) -> Optional[str]:
        cleaned = text
        for marker in ("do not", "must not", "should not", "must", "shall", "required", "يجب", "يلزم", "لا ", "يمنع"):
            cleaned = cleaned.replace(marker, " ")
        cleaned = re.sub(r"[^\w\u0600-\u06FF]+", " ", cleaned).strip()
        return cleaned or None

    def _ensure_inside_workspace(self, path: Path) -> None:
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {path}") from exc
