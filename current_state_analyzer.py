from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Optional


SCHEMA_VERSION = 1
DEFAULT_MAX_FILE_BYTES = 100_000
DEFAULT_MAX_MATCHES_PER_REQUIREMENT = 8


class CurrentStateAnalyzer:
    """Build implementation/test evidence from the actual local workspace.

    The analyzer is read-only. It never executes project code and never calls
    an external provider. Its output is evidence, not a compliance verdict.
    """

    def __init__(
        self,
        workspace_root: Path,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_matches_per_requirement: int = DEFAULT_MAX_MATCHES_PER_REQUIREMENT,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.max_file_bytes = max_file_bytes
        self.max_matches_per_requirement = max_matches_per_requirement

        if not self.workspace_root.exists():
            raise ValueError(f"Workspace does not exist: {self.workspace_root}")
        if not self.workspace_root.is_dir():
            raise ValueError(f"Workspace is not a directory: {self.workspace_root}")

    def analyze(
        self,
        specification: dict[str, Any],
        manifest: Optional[dict[str, Any]] = None,
        execution_evidence: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        requirements = specification.get("requirements", [])
        if not isinstance(requirements, list):
            requirements = []

        file_records = self._candidate_files(manifest)
        requirement_evidence: list[dict[str, Any]] = []

        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            requirement_evidence.append(
                self._analyze_requirement(
                    requirement,
                    file_records,
                    execution_evidence or {},
                )
            )

        test_files = [
            record["path"]
            for record in file_records
            if record["is_test"]
        ]
        implementation_files = [
            record["path"]
            for record in file_records
            if record["is_implementation"]
        ]

        return {
            "schema_version": SCHEMA_VERSION,
            "analyzer": {
                "name": "CurrentStateAnalyzer",
                "version": "v1",
            },
            "workspace": {
                "root": str(self.workspace_root),
            },
            "summary": {
                "scanned_file_count": len(file_records),
                "implementation_file_count": len(implementation_files),
                "test_file_count": len(test_files),
                "implementation_files": implementation_files,
                "test_files": test_files,
            },
            "requirements": requirement_evidence,
            "execution_evidence": execution_evidence or {},
        }

    def _candidate_files(self, manifest: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
        if manifest and isinstance(manifest.get("files"), list):
            paths: list[str] = []
            for item in manifest["files"]:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                if not path or item.get("is_sensitive"):
                    continue
                paths.append(str(path))
            return self._read_records(paths)

        paths = []
        for path in self.workspace_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.workspace_root)
            if any(
                part == ".git"
                or part.startswith(".agent_")
                or part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", "node_modules", "build", "dist"}
                for part in relative.parts[:-1]
            ):
                continue
            paths.append(relative.as_posix())
        return self._read_records(paths)

    def _read_records(self, paths: Iterable[str]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        implementation_extensions = {
            ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go",
            ".rs", ".c", ".cc", ".cpp", ".cxx", ".cs", ".rb", ".php",
            ".swift", ".scala", ".dart", ".vue", ".svelte",
        }

        for relative in sorted(set(paths), key=str.lower):
            path = (self.workspace_root / relative).resolve()
            self._ensure_inside_workspace(path)
            if not path.is_file():
                continue

            try:
                if path.stat().st_size > self.max_file_bytes:
                    continue
                text = path.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeDecodeError):
                continue

            name = path.name.lower()
            record = {
                "path": path.relative_to(self.workspace_root).as_posix(),
                "text": text,
                "is_test": (
                    name.startswith("test_")
                    or name.endswith("_test.py")
                    or "/tests/" in f"/{path.relative_to(self.workspace_root).as_posix().lower()}"
                    or "/test/" in f"/{path.relative_to(self.workspace_root).as_posix().lower()}"
                ),
                "is_implementation": path.suffix.lower() in implementation_extensions,
            }
            records.append(record)

        return records

    def _analyze_requirement(
        self,
        requirement: dict[str, Any],
        file_records: list[dict[str, Any]],
        execution_evidence: dict[str, Any],
    ) -> dict[str, Any]:
        requirement_id = str(requirement.get("requirement_id", ""))
        text = str(requirement.get("text", ""))
        tokens = self._tokens(text)
        implementation_matches: list[dict[str, Any]] = []
        test_matches: list[dict[str, Any]] = []

        for record in file_records:
            score_tokens = sum(
                1 for token in tokens if re.search(rf"(?<!\w){re.escape(token)}(?!\w)", record["text"], re.IGNORECASE)
            )
            if score_tokens == 0:
                continue

            match = {
                "path": record["path"],
                "token_hits": score_tokens,
            }
            if record["is_test"]:
                if len(test_matches) < self.max_matches_per_requirement:
                    test_matches.append(match)
            elif record["is_implementation"]:
                if len(implementation_matches) < self.max_matches_per_requirement:
                    implementation_matches.append(match)

        execution_result = execution_evidence.get(requirement_id)
        if execution_result is None:
            execution_result = execution_evidence.get(text)

        return {
            "requirement_id": requirement_id,
            "implementation_evidence": implementation_matches,
            "test_evidence": test_matches,
            "execution_evidence": execution_result,
            "evidence_level": self._evidence_level(
                implementation_matches,
                test_matches,
                execution_result,
            ),
        }

    @staticmethod
    def _tokens(text: str) -> list[str]:
        backticked = re.findall(r"`([^`]+)`", text)
        function_names = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", text)
        identifiers = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b", text)
        candidates = backticked + function_names + identifiers

        ignored = {
            "should", "must", "shall", "required", "return", "returns",
            "with", "from", "that", "this", "only", "project", "file",
            "implementation", "tests", "test", "function", "error",
        }
        result: list[str] = []
        seen: set[str] = set()
        for token in candidates:
            cleaned = token.strip("`.,:;()[]{}\"").strip()
            if len(cleaned) < 2 or cleaned.casefold() in ignored:
                continue
            if cleaned.casefold() not in seen:
                seen.add(cleaned.casefold())
                result.append(cleaned)
        return result[:20]

    @staticmethod
    def _evidence_level(
        implementation_matches: list[dict[str, Any]],
        test_matches: list[dict[str, Any]],
        execution_result: Any,
    ) -> str:
        if execution_result is not None:
            return "EXECUTION_EVIDENCE"
        if implementation_matches and test_matches:
            return "IMPLEMENTATION_AND_TEST_EVIDENCE"
        if implementation_matches:
            return "IMPLEMENTATION_EVIDENCE"
        if test_matches:
            return "TEST_EVIDENCE_ONLY"
        return "NO_DIRECT_EVIDENCE"

    def _ensure_inside_workspace(self, path: Path) -> None:
        try:
            path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError(f"Path escapes workspace: {path}") from exc
