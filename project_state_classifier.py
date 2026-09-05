from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# PROJECT STATE CLASSIFIER v4
# ============================================================
#
# Automatically classifies a project as:
#
#   BUILD
#   CONTINUE
#   MAINTAIN
#   REPAIR
#   CONFLICT
#   UNKNOWN
#
# IMPORTANT DECISION RULES
# ------------------------
#
# 1. Confirmed specification conflict is a hard safety stop.
# 2. Confirmed project failure is a hard REPAIR state.
# 3. REPAIR confidence is intentionally high when failure
#    evidence is explicit. It must not fall to 0.5 merely
#    because MAINTAIN also has strong evidence.
# 4. Empty workspace without design/specification -> UNKNOWN.
# 5. Empty/minimal workspace with design/specification -> BUILD.
# 6. Existing implementation + unfinished requirements -> CONTINUE.
# 7. Stable complete implementation -> MAINTAIN.
#
# This module performs local classification only.
# No network/API inference is performed.
# ============================================================


SCHEMA_VERSION = 4

VALID_STATES = {
    "BUILD",
    "CONTINUE",
    "MAINTAIN",
    "REPAIR",
    "CONFLICT",
    "UNKNOWN",
}

AUTONOMOUS_STATES = {
    "BUILD",
    "CONTINUE",
    "MAINTAIN",
    "REPAIR",
}


@dataclass
class Classification:
    state: str
    confidence: float
    rationale: str
    scores: Dict[str, float]
    unresolved_requirements: int
    evidence: Dict[str, Any]
    autonomous_start_allowed: bool


class ProjectStateClassifier:
    """
    Infer project state from a scanner-style manifest.

    The decision process has three layers:

        1. Normalize evidence
        2. Apply hard safety/state gates
        3. Use weighted scoring for ordinary states

    Hard gates take precedence over ordinary scoring.
    """

    def __init__(self, autonomous_threshold: float = 0.60):
        self.autonomous_threshold = autonomous_threshold

    # ========================================================
    # PUBLIC API
    # ========================================================

    def classify(self, manifest: Dict[str, Any]) -> Classification:
        evidence = self._normalize_evidence(manifest)

        scores = {
            "BUILD": 0.0,
            "CONTINUE": 0.0,
            "MAINTAIN": 0.0,
            "REPAIR": 0.0,
            "CONFLICT": 0.0,
            "UNKNOWN": 0.0,
        }

        unresolved = evidence["unresolved_requirements"]

        # ----------------------------------------------------
        # Ordinary evidence scoring
        # ----------------------------------------------------

        self._score_build(scores, evidence)
        self._score_continue(scores, evidence, unresolved)
        self._score_maintain(scores, evidence, unresolved)
        self._score_repair(scores, evidence)
        self._score_conflict(scores, evidence)

        # ----------------------------------------------------
        # HARD GATE 1: specification conflict
        # ----------------------------------------------------

        if evidence["spec_conflict"]:
            scores["CONFLICT"] = max(scores["CONFLICT"], 200.0)

            return self._build_result(
                state="CONFLICT",
                scores=scores,
                evidence=evidence,
                unresolved_requirements=unresolved,
                rationale=(
                    "Specification or design evidence contains "
                    "unresolved contradictions; autonomous execution "
                    "is not allowed."
                ),
                confidence_override=0.95,
            )

        # ----------------------------------------------------
        # HARD GATE 2: confirmed failure
        # ----------------------------------------------------
        #
        # This is the key correction from v3.
        #
        # Failure is not a competition between MAINTAIN and REPAIR.
        # Once failure is explicitly observed, the project state is
        # REPAIR and its confidence reflects the certainty of the
        # failure evidence.
        # ----------------------------------------------------

        if evidence["confirmed_failure"]:
            scores["REPAIR"] = max(scores["REPAIR"], 140.0)

            return self._build_result(
                state="REPAIR",
                scores=scores,
                evidence=evidence,
                unresolved_requirements=unresolved,
                rationale=(
                    "Confirmed project failure detected "
                    "(tests, build, syntax, or equivalent); "
                    "repair takes precedence over maintenance "
                    "and continuation."
                ),
                confidence_override=0.95,
            )

        # ----------------------------------------------------
        # Empty/minimal workspace guard
        # ----------------------------------------------------

        implementation_files = evidence["implementation_files"]
        has_design_docs = (
            evidence["has_specification"]
            or evidence["has_readme"]
        )

        if implementation_files == 0 and not has_design_docs:
            scores["UNKNOWN"] = 100.0

            return self._build_result(
                state="UNKNOWN",
                scores=scores,
                evidence=evidence,
                unresolved_requirements=unresolved,
                rationale=(
                    "Workspace contains insufficient evidence to determine "
                    "whether autonomous construction should begin."
                ),
                confidence_override=0.95,
            )

        # ----------------------------------------------------
        # Empty/minimal workspace WITH documentation
        # ----------------------------------------------------

        if implementation_files == 0 and has_design_docs:
            scores["BUILD"] = max(scores["BUILD"], 120.0)

        # ----------------------------------------------------
        # Ordinary state selection
        # ----------------------------------------------------

        candidate_states = [
            "BUILD",
            "CONTINUE",
            "MAINTAIN",
            "REPAIR",
            "CONFLICT",
        ]

        best_state = max(
            candidate_states,
            key=lambda state: scores[state],
        )

        best_score = scores[best_state]

        if best_score <= 0:
            scores["UNKNOWN"] = 100.0

            return self._build_result(
                state="UNKNOWN",
                scores=scores,
                evidence=evidence,
                unresolved_requirements=unresolved,
                rationale=(
                    "No sufficiently strong project-state evidence "
                    "was found."
                ),
                confidence_override=0.95,
            )

        confidence = self._confidence(
            scores,
            best_state,
        )

        return self._build_result(
            state=best_state,
            scores=scores,
            evidence=evidence,
            unresolved_requirements=unresolved,
            rationale=(
                f"{best_state} has the strongest evidence score "
                f"({best_score:g})."
            ),
            confidence_override=confidence,
        )

    # ========================================================
    # EVIDENCE NORMALIZATION
    # ========================================================

    def _normalize_evidence(
        self,
        manifest: Dict[str, Any],
    ) -> Dict[str, Any]:

        files = manifest.get("files", [])
        tests = manifest.get("tests", {})
        notes = manifest.get("notes", {})
        git = manifest.get("git", {})

        if not isinstance(files, list):
            files = []

        if not isinstance(tests, dict):
            tests = {}

        if not isinstance(notes, dict):
            notes = {}

        if not isinstance(git, dict):
            git = {}

        file_paths: List[str] = []

        for item in files:
            if isinstance(item, str):
                file_paths.append(item)
                continue

            if isinstance(item, dict):
                path = (
                    item.get("path")
                    or item.get("relative_path")
                    or item.get("name")
                )

                if path:
                    file_paths.append(str(path))

        normalized_paths = [
            p.replace("\\", "/").lower()
            for p in file_paths
        ]

        excluded_fragments = (
            "/node_modules/",
            "/build/",
            "/dist/",
            "/.git/",
            "/.venv/",
            "/venv/",
            "/__pycache__/",
            "/.pytest_cache/",
        )

        relevant_paths = [
            p
            for p in normalized_paths
            if not any(
                fragment in f"/{p}/"
                for fragment in excluded_fragments
            )
        ]

        implementation_extensions = {
            ".py",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".java",
            ".kt",
            ".go",
            ".rs",
            ".cpp",
            ".cc",
            ".cxx",
            ".c",
            ".cs",
            ".rb",
            ".php",
            ".swift",
            ".scala",
            ".dart",
            ".vue",
            ".svelte",
        }

        implementation_files = sum(
            1
            for p in relevant_paths
            if Path(p).suffix.lower()
            in implementation_extensions
        )

        test_files = [
            p
            for p in relevant_paths
            if (
                Path(p).name.lower().startswith("test_")
                or Path(p).name.lower().endswith("_test.py")
                or "/tests/" in f"/{p}"
                or "/test/" in f"/{p}"
            )
        ]

        documentation_names = {
            "readme.md",
            "readme.txt",
            "readme.rst",
            "design.md",
            "architecture.md",
            "requirements.md",
            "specification.md",
            "spec.md",
            "project_spec.md",
            "vision.md",
            "rules.md",
            "roadmap.md",
        }

        has_readme = any(
            Path(p).name.lower()
            in {
                "readme.md",
                "readme.txt",
                "readme.rst",
            }
            for p in relevant_paths
        )

        spec_patterns = (
            "/docs/",
            "/doc/",
            "/spec/",
            "/specs/",
            "/design/",
            "/architecture/",
            "/requirements/",
        )

        specification_files = [
            p
            for p in relevant_paths
            if (
                Path(p).name.lower() in documentation_names
                or any(
                    fragment in f"/{p}"
                    for fragment in spec_patterns
                )
            )
        ]

        has_specification = bool(specification_files)

        unresolved = (
            self._extract_unresolved_requirements(
                manifest,
                notes,
            )
        )

        spec_conflict = self._detect_spec_conflict(
            manifest,
            notes,
        )

        (
            confirmed_failure,
            failure_reasons,
        ) = self._detect_failure(
            manifest,
            tests,
            notes,
        )

        syntax_error = self._detect_bool(
            tests,
            (
                "syntax_error",
                "syntax_errors",
                "has_syntax_error",
                "syntax_failure",
            ),
        )

        build_failure = self._detect_bool(
            tests,
            (
                "build_failed",
                "build_failure",
                "build_error",
                "has_build_error",
            ),
        )

        tests_failed = self._detect_bool(
            tests,
            (
                "tests_failed",
                "test_failure",
                "test_failed",
                "has_test_failure",
                "failing_tests",
            ),
        )

        explicit_complete = self._detect_bool(
            manifest,
            (
                "complete",
                "project_complete",
                "specification_satisfied",
                "all_requirements_satisfied",
            ),
        )

        explicit_partial = self._detect_bool(
            manifest,
            (
                "partial",
                "project_partial",
                "incomplete",
            ),
        )

        explicit_broken = self._detect_bool(
            manifest,
            (
                "broken",
                "project_broken",
                "repair_required",
            ),
        )

        stable = self._detect_bool(
            manifest,
            (
                "stable",
                "project_stable",
                "healthy",
            ),
        )

        git_dirty = bool(
            git.get("dirty")
            or git.get("changes")
            or git.get("modified")
        )

        return {
            "file_count": len(relevant_paths),
            "implementation_files": implementation_files,
            "test_file_count": len(test_files),
            "test_files": test_files,
            "has_readme": has_readme,
            "has_specification": has_specification,
            "specification_files": specification_files,
            "unresolved_requirements": unresolved,
            "spec_conflict": spec_conflict,
            "confirmed_failure": confirmed_failure,
            "failure_reasons": failure_reasons,
            "syntax_error": syntax_error,
            "build_failure": build_failure,
            "tests_failed": tests_failed,
            "explicit_complete": explicit_complete,
            "explicit_partial": explicit_partial,
            "explicit_broken": explicit_broken,
            "stable": stable,
            "git_dirty": git_dirty,
        }

    # ========================================================
    # SCORING
    # ========================================================

    def _score_build(
        self,
        scores: Dict[str, float],
        evidence: Dict[str, Any],
    ) -> None:

        if evidence["has_specification"]:
            scores["BUILD"] += 70

        if evidence["has_readme"]:
            scores["BUILD"] += 20

        if evidence["implementation_files"] == 0:
            if evidence["has_specification"]:
                scores["BUILD"] += 50

        elif (
            evidence["implementation_files"] <= 2
            and evidence["has_specification"]
        ):
            scores["BUILD"] += 20

    def _score_continue(
        self,
        scores: Dict[str, float],
        evidence: Dict[str, Any],
        unresolved: int,
    ) -> None:

        if (
            evidence["implementation_files"] > 0
            and evidence["has_specification"]
        ):
            scores["CONTINUE"] += 60

        if unresolved > 0:
            scores["CONTINUE"] += min(
                80,
                unresolved * 10,
            )

        if evidence["explicit_partial"]:
            scores["CONTINUE"] += 50

    def _score_maintain(
        self,
        scores: Dict[str, float],
        evidence: Dict[str, Any],
        unresolved: int,
    ) -> None:

        if evidence["implementation_files"] > 0:
            scores["MAINTAIN"] += 35

        if evidence["explicit_complete"]:
            scores["MAINTAIN"] += 50

        if evidence["stable"]:
            scores["MAINTAIN"] += 40

        if (
            unresolved == 0
            and evidence["has_specification"]
        ):
            scores["MAINTAIN"] += 30

        if evidence["git_dirty"]:
            scores["MAINTAIN"] += 5

    def _score_repair(
        self,
        scores: Dict[str, float],
        evidence: Dict[str, Any],
    ) -> None:

        if evidence["tests_failed"]:
            scores["REPAIR"] += 100

        if evidence["build_failure"]:
            scores["REPAIR"] += 120

        if evidence["syntax_error"]:
            scores["REPAIR"] += 130

        if evidence["explicit_broken"]:
            scores["REPAIR"] += 100

    def _score_conflict(
        self,
        scores: Dict[str, float],
        evidence: Dict[str, Any],
    ) -> None:

        if evidence["spec_conflict"]:
            scores["CONFLICT"] = 200

    # ========================================================
    # FAILURE DETECTION
    # ========================================================

    def _detect_failure(
        self,
        manifest: Dict[str, Any],
        tests: Dict[str, Any],
        notes: Dict[str, Any],
    ) -> Tuple[bool, List[str]]:

        reasons: List[str] = []

        test_fail = self._detect_bool(
            tests,
            (
                "tests_failed",
                "test_failure",
                "test_failed",
                "has_test_failure",
                "failing_tests",
            ),
        )

        build_fail = self._detect_bool(
            tests,
            (
                "build_failed",
                "build_failure",
                "build_error",
                "has_build_error",
            ),
        )

        syntax_fail = self._detect_bool(
            tests,
            (
                "syntax_error",
                "syntax_errors",
                "has_syntax_error",
                "syntax_failure",
            ),
        )

        broken = self._detect_bool(
            manifest,
            (
                "broken",
                "project_broken",
                "repair_required",
            ),
        )

        if test_fail:
            reasons.append("failing tests")

        if build_fail:
            reasons.append("build failure")

        if syntax_fail:
            reasons.append("syntax error")

        if broken:
            reasons.append("project marked broken")

        # Numeric test failure counts.
        failed_counts = (
            tests.get("failed"),
            tests.get("failed_tests"),
            tests.get("failure_count"),
            tests.get("failures"),
        )

        for value in failed_counts:
            if isinstance(value, bool):
                if value:
                    reasons.append(
                        "test failures reported"
                    )
                    break

            elif isinstance(value, (int, float)):
                if value > 0:
                    reasons.append(
                        "non-zero failing-test count"
                    )
                    break

        # Status strings.
        status_candidates = [
            tests.get("status"),
            tests.get("result"),
            tests.get("test_status"),
            tests.get("build_status"),
            notes.get("test_status"),
            notes.get("build_status"),
        ]

        failure_words = {
            "fail",
            "failed",
            "failure",
            "failing",
            "broken",
            "error",
            "errors",
            "red",
            "syntax_error",
            "build_error",
        }

        for status in status_candidates:
            if isinstance(status, str):
                normalized = status.strip().lower()

                if normalized in failure_words:
                    reasons.append(
                        f"status={normalized}"
                    )

        # Explicit failure/error lists.
        failure_lists = [
            tests.get("failures"),
            tests.get("errors"),
            manifest.get("errors"),
            notes.get("errors"),
        ]

        for value in failure_lists:
            if isinstance(value, list) and value:
                reasons.append(
                    "explicit failure/error entries"
                )
                break

        # Deduplicate.
        deduped: List[str] = []
        seen = set()

        for reason in reasons:
            if reason not in seen:
                seen.add(reason)
                deduped.append(reason)

        return bool(deduped), deduped

    # ========================================================
    # SPECIFICATION HELPERS
    # ========================================================

    def _detect_spec_conflict(
        self,
        manifest: Dict[str, Any],
        notes: Dict[str, Any],
    ) -> bool:

        candidates = [
            manifest.get("spec_conflict"),
            manifest.get("specification_conflict"),
            manifest.get("conflict"),
            notes.get("spec_conflict"),
            notes.get("specification_conflict"),
            notes.get("conflict"),
        ]

        for value in candidates:
            if isinstance(value, bool) and value:
                return True

            if isinstance(value, str):
                if value.strip().lower() in {
                    "true",
                    "yes",
                    "conflict",
                    "conflicting",
                }:
                    return True

        conflicts = manifest.get("conflicts")

        if isinstance(conflicts, list) and conflicts:
            return True

        return False

    def _extract_unresolved_requirements(
        self,
        manifest: Dict[str, Any],
        notes: Dict[str, Any],
    ) -> int:

        direct_candidates = [
            manifest.get("unresolved_requirements"),
            manifest.get("unresolved_count"),
            notes.get("unresolved_requirements"),
            notes.get("unresolved_count"),
        ]

        for value in direct_candidates:
            if isinstance(value, int) and value >= 0:
                return value

            if isinstance(value, float) and value >= 0:
                return int(value)

            if isinstance(value, list):
                return len(value)

        requirements = manifest.get("requirements")

        if isinstance(requirements, list):
            count = 0

            for item in requirements:
                if isinstance(item, str):
                    if not self._is_requirement_satisfied_text(
                        item
                    ):
                        count += 1

                elif isinstance(item, dict):
                    status = str(
                        item.get("status", "")
                    ).strip().lower()

                    satisfied = item.get("satisfied")

                    if satisfied is False:
                        count += 1

                    elif status in {
                        "todo",
                        "pending",
                        "open",
                        "unresolved",
                        "incomplete",
                        "missing",
                    }:
                        count += 1

            return count

        return 0

    @staticmethod
    def _is_requirement_satisfied_text(
        text: str,
    ) -> bool:

        normalized = text.strip().lower()

        if normalized.startswith("[x]"):
            return True

        if normalized.startswith("done:"):
            return True

        if normalized.startswith("complete:"):
            return True

        return False

    # ========================================================
    # GENERIC HELPERS
    # ========================================================

    @staticmethod
    def _detect_bool(
        data: Dict[str, Any],
        keys: Tuple[str, ...],
    ) -> bool:

        for key in keys:
            if key not in data:
                continue

            value = data[key]

            if isinstance(value, bool):
                if value:
                    return True

            elif isinstance(value, int):
                if value != 0:
                    return True

            elif isinstance(value, str):
                if value.strip().lower() in {
                    "true",
                    "yes",
                    "1",
                    "failed",
                    "fail",
                    "broken",
                    "error",
                    "errors",
                }:
                    return True

            elif isinstance(value, list):
                if value:
                    return True

        return False

    # ========================================================
    # CONFIDENCE
    # ========================================================

    def _confidence(
        self,
        scores: Dict[str, float],
        state: str,
    ) -> float:

        best = max(
            scores.get(state, 0.0),
            0.0,
        )

        competing = [
            value
            for name, value in scores.items()
            if (
                name != state
                and name != "UNKNOWN"
            )
        ]

        second = max(
            competing,
            default=0.0,
        )

        if best <= 0:
            return 0.0

        margin = max(
            best - second,
            0.0,
        )

        raw = (
            0.50
            + (
                margin / max(best, 1.0)
            ) * 0.45
        )

        return round(
            max(0.0, min(raw, 0.99)),
            4,
        )

    # ========================================================
    # RESULT CONSTRUCTION
    # ========================================================

    def _build_result(
        self,
        state: str,
        scores: Dict[str, float],
        evidence: Dict[str, Any],
        unresolved_requirements: int,
        rationale: str,
        confidence_override: Optional[float] = None,
    ) -> Classification:

        if state not in VALID_STATES:
            raise ValueError(
                f"Invalid project state: {state}"
            )

        confidence = (
            self._confidence(scores, state)
            if confidence_override is None
            else confidence_override
        )

        autonomous = (
            state in AUTONOMOUS_STATES
            and confidence >= self.autonomous_threshold
        )

        # Safety states can never auto-start.
        if state in {
            "CONFLICT",
            "UNKNOWN",
        }:
            autonomous = False

        return Classification(
            state=state,
            confidence=confidence,
            rationale=rationale,
            scores={
                key: round(
                    float(value),
                    4,
                )
                for key, value in scores.items()
            },
            unresolved_requirements=unresolved_requirements,
            evidence=evidence,
            autonomous_start_allowed=autonomous,
        )


# ============================================================
# SYNTHETIC TESTS
# ============================================================

def _write_json(
    path: Path,
    payload: Dict[str, Any],
) -> None:

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _run_synthetic_tests() -> None:

    print("=" * 70)
    print("PROJECT STATE CLASSIFIER SYNTHETIC TEST")
    print("=" * 70)

    classifier = ProjectStateClassifier()

    test_root = Path(
        tempfile.mkdtemp(
            prefix="project_state_classifier_test_"
        )
    )

    try:
        # ----------------------------------------------------
        # TEST 1
        # ----------------------------------------------------
        print("\n" + "-" * 70)
        print("TEST 1: NEW PROJECT + SPECIFICATION -> BUILD")
        print("-" * 70)

        manifest = {
            "files": [
                {"path": "README.md"},
                {"path": "docs/specification.md"},
            ],
            "tests": {
                "tests_failed": False,
            },
            "requirements": [
                {"status": "todo"},
            ],
        }

        result = classifier.classify(manifest)

        print(
            "New project with full design"
            f"{' ' * 28}-> "
            f"{result.state:<9}"
            f" confidence={result.confidence}"
        )
        print(
            f"Rationale: {result.rationale}"
        )
        print(
            "BUILD classification:",
            "PASS ✅"
            if result.state == "BUILD"
            else "FAIL ❌",
        )

        assert result.state == "BUILD"

        # ----------------------------------------------------
        # TEST 2
        # ----------------------------------------------------
        print("\n" + "-" * 70)
        print("TEST 2: PARTIAL PROJECT -> CONTINUE")
        print("-" * 70)

        manifest = {
            "files": [
                {"path": "README.md"},
                {"path": "docs/specification.md"},
                {"path": "app.py"},
                {"path": "services.py"},
                {"path": "models.py"},
                {"path": "test_app.py"},
            ],
            "requirements": [
                {"status": "done"},
                {"status": "pending"},
                {"status": "pending"},
                {"status": "pending"},
                {"status": "pending"},
                {"status": "pending"},
                {"status": "pending"},
                {"status": "done"},
                {"status": "done"},
            ],
            "tests": {
                "tests_failed": False,
            },
        }

        result = classifier.classify(manifest)

        print(
            "Existing project with unfinished specification"
            f" -> {result.state:<9}"
            f" confidence={result.confidence}"
        )
        print(
            f"Unresolved requirements: "
            f"{result.unresolved_requirements}"
        )
        print(
            "CONTINUE classification:",
            "PASS ✅"
            if result.state == "CONTINUE"
            else "FAIL ❌",
        )

        assert result.state == "CONTINUE"

        # ----------------------------------------------------
        # TEST 3
        # ----------------------------------------------------
        print("\n" + "-" * 70)
        print("TEST 3: COMPLETED STABLE PROJECT -> MAINTAIN")
        print("-" * 70)

        manifest = {
            "files": [
                {"path": "README.md"},
                {"path": "docs/specification.md"},
                {"path": "app.py"},
                {"path": "services.py"},
                {"path": "models.py"},
                {"path": "test_app.py"},
            ],
            "requirements": [
                {"status": "done"},
                {"status": "done"},
                {"status": "done"},
                {"status": "done"},
            ],
            "complete": True,
            "stable": True,
            "tests": {
                "tests_failed": False,
                "build_failed": False,
                "syntax_error": False,
            },
        }

        result = classifier.classify(manifest)

        print(
            "Stable project with satisfied specification"
            f" -> {result.state:<9}"
            f" confidence={result.confidence}"
        )
        print(
            "MAINTAIN classification:",
            "PASS ✅"
            if result.state == "MAINTAIN"
            else "FAIL ❌",
        )

        assert result.state == "MAINTAIN"

        # ----------------------------------------------------
        # TEST 4
        # ----------------------------------------------------
        print("\n" + "-" * 70)
        print("TEST 4: BROKEN PROJECT -> REPAIR")
        print("-" * 70)

        manifest = {
            "files": [
                {"path": "README.md"},
                {"path": "docs/specification.md"},
                {"path": "app.py"},
                {"path": "services.py"},
                {"path": "models.py"},
                {"path": "test_app.py"},
            ],
            "requirements": [
                {"status": "done"},
                {"status": "done"},
                {"status": "done"},
            ],
            "complete": True,
            "stable": True,
            "tests": {
                "tests_failed": True,
                "failed": 2,
                "status": "failed",
            },
        }

        result = classifier.classify(manifest)

        print(
            "Existing project with failing tests"
            f" -> {result.state:<9}"
            f" confidence={result.confidence}"
        )
        print(
            "Failure evidence:",
            ", ".join(
                result.evidence["failure_reasons"]
            ),
        )
        print(
            "REPAIR classification:",
            "PASS ✅"
            if result.state == "REPAIR"
            else "FAIL ❌",
        )

        assert result.state == "REPAIR"
        assert result.confidence >= 0.90

        # ----------------------------------------------------
        # TEST 5
        # ----------------------------------------------------
        print("\n" + "-" * 70)
        print("TEST 5: CONFLICTING SPECIFICATION -> CONFLICT")
        print("-" * 70)

        manifest = {
            "files": [
                {"path": "README.md"},
                {"path": "docs/specification.md"},
                {"path": "docs/architecture.md"},
                {"path": "app.py"},
            ],
            "spec_conflict": True,
            "requirements": [
                {"status": "pending"},
            ],
            "tests": {
                "tests_failed": False,
            },
        }

        result = classifier.classify(manifest)

        print(
            "Contradictory specification evidence"
            f" -> {result.state:<9}"
            f" confidence={result.confidence}"
        )
        print(
            f"Rationale: {result.rationale}"
        )
        print(
            "CONFLICT classification:",
            "PASS ✅"
            if result.state == "CONFLICT"
            else "FAIL ❌",
        )

        assert result.state == "CONFLICT"
        assert result.autonomous_start_allowed is False

        # ----------------------------------------------------
        # TEST 6
        # ----------------------------------------------------
        print("\n" + "-" * 70)
        print(
            "TEST 6: EMPTY WORKSPACE WITHOUT SPECIFICATION -> UNKNOWN"
        )
        print("-" * 70)

        manifest = {
            "files": [],
            "tests": {},
            "requirements": [],
        }

        result = classifier.classify(manifest)

        print(
            "Empty workspace without specification"
            f" -> {result.state:<9}"
            f" confidence={result.confidence}"
        )
        print(
            f"Rationale: {result.rationale}"
        )
        print(
            "UNKNOWN classification:",
            "PASS ✅"
            if result.state == "UNKNOWN"
            else "FAIL ❌",
        )

        assert result.state == "UNKNOWN"
        assert result.autonomous_start_allowed is False

        # ----------------------------------------------------
        # TEST 7
        # ----------------------------------------------------
        print("\n" + "-" * 70)
        print(
            "TEST 7: EMPTY WORKSPACE + README -> BUILD"
        )
        print("-" * 70)

        manifest = {
            "files": [
                {"path": "README.md"},
            ],
            "tests": {},
            "requirements": [],
        }

        result = classifier.classify(manifest)

        print(
            "Empty workspace with README"
            f" -> {result.state:<9}"
            f" confidence={result.confidence}"
        )
        print(
            "README-driven BUILD classification:",
            "PASS ✅"
            if result.state == "BUILD"
            else "FAIL ❌",
        )

        assert result.state == "BUILD"

        # ----------------------------------------------------
        # TEST 8
        # ----------------------------------------------------
        print("\n" + "-" * 70)
        print(
            "TEST 8: SYNTAX ERROR -> REPAIR OVERRIDES MAINTAIN"
        )
        print("-" * 70)

        manifest = {
            "files": [
                {"path": "README.md"},
                {"path": "docs/specification.md"},
                {"path": "app.py"},
                {"path": "test_app.py"},
            ],
            "complete": True,
            "stable": True,
            "requirements": [
                {"status": "done"},
            ],
            "tests": {
                "syntax_error": True,
                "status": "error",
            },
        }

        result = classifier.classify(manifest)

        print(
            "Completed project with syntax error"
            f" -> {result.state:<9}"
            f" confidence={result.confidence}"
        )
        print(
            "REPAIR precedence:",
            "PASS ✅"
            if result.state == "REPAIR"
            else "FAIL ❌",
        )

        assert result.state == "REPAIR"
        assert result.confidence >= 0.90

        # ----------------------------------------------------
        # TEST 9
        # ----------------------------------------------------
        print("\n" + "-" * 70)
        print(
            "TEST 9: BUILD FAILURE -> REPAIR"
        )
        print("-" * 70)

        manifest = {
            "files": [
                {"path": "README.md"},
                {"path": "docs/specification.md"},
                {"path": "app.py"},
                {"path": "test_app.py"},
            ],
            "complete": True,
            "stable": True,
            "tests": {
                "build_failed": True,
                "status": "failed",
            },
        }

        result = classifier.classify(manifest)

        print(
            "Completed project with build failure"
            f" -> {result.state:<9}"
            f" confidence={result.confidence}"
        )
        print(
            "BUILD FAILURE -> REPAIR:",
            "PASS ✅"
            if result.state == "REPAIR"
            else "FAIL ❌",
        )

        assert result.state == "REPAIR"
        assert result.confidence >= 0.90

        # ----------------------------------------------------
        # TEST 10
        # ----------------------------------------------------
        print("\n" + "-" * 70)
        print(
            "TEST 10: REPAIR MUST ALLOW AUTONOMOUS START"
        )
        print("-" * 70)

        print(
            f"REPAIR confidence: "
            f"{result.confidence}"
        )

        print(
            f"Autonomous start allowed: "
            f"{result.autonomous_start_allowed}"
        )

        assert result.state == "REPAIR"
        assert result.confidence >= 0.90
        assert (
            result.autonomous_start_allowed is True
        )

        print(
            "Autonomous REPAIR start:",
            "PASS ✅"
            if result.autonomous_start_allowed
            else "FAIL ❌",
        )

        # ----------------------------------------------------
        # TEST 11
        # ----------------------------------------------------
        print("\n" + "-" * 70)
        print(
            "TEST 11: UNKNOWN/CONFLICT MUST NEVER AUTOSTART"
        )
        print("-" * 70)

        unknown_manifest = {
            "files": [],
            "tests": {},
        }

        unknown_result = classifier.classify(
            unknown_manifest
        )

        conflict_manifest = {
            "files": [
                {"path": "README.md"},
                {"path": "docs/specification.md"},
            ],
            "spec_conflict": True,
        }

        conflict_result = classifier.classify(
            conflict_manifest
        )

        print(
            "UNKNOWN autonomous start:",
            unknown_result.autonomous_start_allowed,
        )
        print(
            "CONFLICT autonomous start:",
            conflict_result.autonomous_start_allowed,
        )

        assert (
            unknown_result.autonomous_start_allowed
            is False
        )
        assert (
            conflict_result.autonomous_start_allowed
            is False
        )

        print(
            "Safety-state autostart block:",
            "PASS ✅"
        )

        # ----------------------------------------------------
        # Final result
        # ----------------------------------------------------

        final_result = {
            "schema_version": SCHEMA_VERSION,
            "tests": {
                "total": 11,
                "passed": 11,
                "failed": 0,
                "status": "PASS",
            },
        }

        output_path = Path(
            "project_state_classifier_test_result.json"
        )

        _write_json(
            output_path,
            final_result,
        )

        print("\n" + "=" * 70)
        print(
            "PROJECT STATE CLASSIFIER TEST PASSED ✅"
        )
        print("=" * 70)

        print(
            f"Result saved to: "
            f"{output_path.resolve()}"
        )

    except Exception:
        print("\n" + "=" * 70)
        print(
            "PROJECT STATE CLASSIFIER TEST FAILED ❌"
        )
        print("=" * 70)
        raise

    finally:
        shutil.rmtree(
            test_root,
            ignore_errors=True,
        )


# ============================================================
# OPTIONAL MANIFEST CLI
# ============================================================

def classify_manifest_file(
    path: Path,
) -> Classification:

    with path.open(
        "r",
        encoding="utf-8",
    ) as handle:
        manifest = json.load(handle)

    classifier = ProjectStateClassifier()

    return classifier.classify(manifest)


def main() -> None:
    """
    Default:
        python project_state_classifier.py

    Optional:
        python project_state_classifier.py manifest.json
    """

    import sys

    if len(sys.argv) == 1:
        _run_synthetic_tests()
        return

    manifest_path = Path(
        sys.argv[1]
    )

    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Manifest not found: "
            f"{manifest_path}"
        )

    if not manifest_path.is_file():
        raise ValueError(
            f"Manifest path is not a file: "
            f"{manifest_path}"
        )

    result = classify_manifest_file(
        manifest_path
    )

    print("=" * 70)
    print("PROJECT STATE CLASSIFICATION")
    print("=" * 70)

    print(
        f"State: {result.state}"
    )

    print(
        f"Confidence: {result.confidence}"
    )

    print(
        "Unresolved requirements: "
        f"{result.unresolved_requirements}"
    )

    print(
        "Autonomous start allowed: "
        f"{result.autonomous_start_allowed}"
    )

    print(
        f"Rationale: {result.rationale}"
    )

    print("\nScores:")

    for state, score in result.scores.items():
        print(
            f"  {state:<10} {score:g}"
        )

    print("\nFailure evidence:")

    if result.evidence["failure_reasons"]:
        for reason in result.evidence[
            "failure_reasons"
        ]:
            print(
                f"  - {reason}"
            )
    else:
        print("  none")

    print("\nEvidence summary:")

    print(
        json.dumps(
            result.evidence,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()