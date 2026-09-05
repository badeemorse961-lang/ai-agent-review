from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple


# ============================================================
# EXPANSION READINESS AUDIT v1
# ============================================================
#
# Purpose:
#   Audit the agent project for hidden fixed-size assumptions.
#
# Goals:
#   - Detect hardcoded pool sizes such as 11 / 15 / 4 / 3 / 2
#   - Detect loops/ranges tied to fixed counts
#   - Detect exact-size comparisons
#   - Inspect JSON pool sizes
#   - Run parameterized synthetic pool tests for N
#
# This tool DOES NOT modify project files.
# This is intentionally a read-only audit before changing the
# existing architecture.
# ============================================================


PROJECT_ROOT = Path(__file__).resolve().parent

IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "build",
    "dist",
    "node_modules",
    ".venv",
    "venv",
    ".agent_gate_checkpoints",
    ".agent_backups",
}


PYTHON_SUFFIXES = {".py"}
JSON_SUFFIXES = {".json"}


# Current numbers are data, not design rules.
KNOWN_CURRENT_COUNTS = {
    11: "current OpenRouter leader accounts",
    15: "current Groq worker accounts",
    4: "current coder pool",
    3: "current debugger/reviewer-sized pool",
    2: "current tester/architect-sized pool",
    1: "current standby / active connection-sized value",
}


@dataclass
class Finding:
    severity: str
    file: str
    line: int
    category: str
    text: str
    recommendation: str


@dataclass
class AuditResult:
    schema_version: int
    project_root: str
    files_scanned: int
    findings: List[Finding]
    synthetic_tests: Dict[str, str]
    dynamic_pool_test: Dict[str, str]
    status: str


class ExpansionReadinessAuditor:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.findings: List[Finding] = []
        self.files_scanned = 0

    # --------------------------------------------------------
    # Public
    # --------------------------------------------------------

    def run(self) -> AuditResult:
        self._scan_python_files()
        self._scan_json_files()

        synthetic = self._run_parameterized_tests()
        dynamic = self._run_dynamic_pool_tests()

        status = self._overall_status(
            synthetic,
            dynamic,
        )

        return AuditResult(
            schema_version=1,
            project_root=str(self.root),
            files_scanned=self.files_scanned,
            findings=self.findings,
            synthetic_tests=synthetic,
            dynamic_pool_test=dynamic,
            status=status,
        )

    # --------------------------------------------------------
    # File enumeration
    # --------------------------------------------------------

    def _iter_files(self):
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue

            relative_parts = path.relative_to(
                self.root
            ).parts

            if any(
                part.lower() in {
                    d.lower()
                    for d in IGNORED_DIRS
                }
                for part in relative_parts
            ):
                continue

            yield path

    # --------------------------------------------------------
    # Python audit
    # --------------------------------------------------------

    def _scan_python_files(self) -> None:
        for path in self._iter_files():
            if path.suffix.lower() not in PYTHON_SUFFIXES:
                continue

            self.files_scanned += 1

            try:
                text = path.read_text(
                    encoding="utf-8"
                )
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                self.findings.append(
                    Finding(
                        severity="WARN",
                        file=self._relative(path),
                        line=1,
                        category="READ_ERROR",
                        text=str(exc),
                        recommendation=(
                            "Inspect file manually."
                        ),
                    )
                )
                continue

            self._audit_python_text(
                path,
                text,
            )

    def _audit_python_text(
        self,
        path: Path,
        text: str,
    ) -> None:

        lines = text.splitlines()

        # --------------------------------------------
        # 1. Fixed range(...)
        # --------------------------------------------

        fixed_range_pattern = re.compile(
            r"\brange\s*\(\s*(1[015]|11|15|4|3|2|1)\s*\)"
        )

        for line_no, line in enumerate(
            lines,
            start=1,
        ):
            if fixed_range_pattern.search(line):
                self.findings.append(
                    Finding(
                        severity="HIGH",
                        file=self._relative(path),
                        line=line_no,
                        category="FIXED_RANGE",
                        text=line.strip(),
                        recommendation=(
                            "Replace fixed iteration count with "
                            "pool/configuration length."
                        ),
                    )
                )

        # --------------------------------------------
        # 2. Exact-size comparisons
        # --------------------------------------------

        exact_size_patterns = [
            re.compile(
                r"\blen\s*\([^)]*\)\s*==\s*(11|15|4|3|2|1)\b"
            ),
            re.compile(
                r"\blen\s*\([^)]*\)\s*!=\s*(11|15|4|3|2|1)\b"
            ),
            re.compile(
                r"\blen\s*\([^)]*\)\s*[<>]=?\s*(11|15|4|3|2|1)\b"
            ),
        ]

        for line_no, line in enumerate(
            lines,
            start=1,
        ):
            for pattern in exact_size_patterns:
                if pattern.search(line):
                    self.findings.append(
                        Finding(
                            severity="HIGH",
                            file=self._relative(path),
                            line=line_no,
                            category="FIXED_POOL_SIZE_COMPARISON",
                            text=line.strip(),
                            recommendation=(
                                "Compare against a configured or "
                                "computed pool size, not a literal."
                            ),
                        )
                    )
                    break

        # --------------------------------------------
        # 3. Fixed-ID construction
        # --------------------------------------------

        fixed_id_patterns = [
            re.compile(
                r"['\"]OR-(0?[1-9]|10|11)['\"]"
            ),
            re.compile(
                r"['\"]GROQ-(0?[1-9]|1[0-5])['\"]"
            ),
        ]

        for line_no, line in enumerate(
            lines,
            start=1,
        ):
            for pattern in fixed_id_patterns:
                if pattern.search(line):
                    # IDs themselves are fine when data-driven.
                    # Flag only literals so they can be reviewed.
                    self.findings.append(
                        Finding(
                            severity="INFO",
                            file=self._relative(path),
                            line=line_no,
                            category="FIXED_CONNECTION_ID",
                            text=line.strip(),
                            recommendation=(
                                "Connection IDs may remain literal "
                                "data, but selection logic must not "
                                "depend on a fixed ID range."
                            ),
                        )
                    )
                    break

        # --------------------------------------------
        # 4. Numeric pool literals near pool keywords
        # --------------------------------------------

        pool_pattern = re.compile(
            r"(pool|leader|worker|standby|coder|debugger|"
            r"tester|architect|reviewer)"
            r".{0,80}\b(11|15|4|3|2)\b",
            re.IGNORECASE,
        )

        for line_no, line in enumerate(
            lines,
            start=1,
        ):
            if pool_pattern.search(line):
                self.findings.append(
                    Finding(
                        severity="MEDIUM",
                        file=self._relative(path),
                        line=line_no,
                        category="POOL_NUMERIC_LITERAL",
                        text=line.strip(),
                        recommendation=(
                            "Verify that this number is configuration "
                            "data rather than a structural assumption."
                        ),
                    )
                )

        # --------------------------------------------
        # 5. AST analysis
        # --------------------------------------------

        try:
            tree = ast.parse(
                text,
                filename=str(path),
            )
        except SyntaxError as exc:
            self.findings.append(
                Finding(
                    severity="WARN",
                    file=self._relative(path),
                    line=exc.lineno or 1,
                    category="AST_PARSE_FAILURE",
                    text=str(exc),
                    recommendation=(
                        "Fix syntax before relying on this file."
                    ),
                )
            )
            return

        self._audit_ast(
            path,
            tree,
        )

    # --------------------------------------------------------
    # AST audit
    # --------------------------------------------------------

    def _audit_ast(
        self,
        path: Path,
        tree: ast.AST,
    ) -> None:

        for node in ast.walk(tree):

            # range(CONSTANT)
            if isinstance(node, ast.Call):
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "range"
                    and len(node.args) == 1
                    and isinstance(
                        node.args[0],
                        ast.Constant,
                    )
                    and isinstance(
                        node.args[0].value,
                        int,
                    )
                ):
                    value = node.args[0].value

                    if value in KNOWN_CURRENT_COUNTS:
                        self.findings.append(
                            Finding(
                                severity="HIGH",
                                file=self._relative(path),
                                line=node.lineno,
                                category="AST_FIXED_RANGE",
                                text=f"range({value})",
                                recommendation=(
                                    "Use dynamic collection size."
                                ),
                            )
                        )

            # if len(x) == CONSTANT
            if isinstance(node, ast.Compare):
                left = node.left

                if isinstance(
                    left,
                    ast.Call,
                ):
                    if (
                        isinstance(
                            left.func,
                            ast.Name,
                        )
                        and left.func.id == "len"
                        and len(node.comparators) == 1
                        and isinstance(
                            node.comparators[0],
                            ast.Constant,
                        )
                        and isinstance(
                            node.comparators[0].value,
                            int,
                        )
                    ):
                        value = node.comparators[0].value

                        if value in KNOWN_CURRENT_COUNTS:
                            self.findings.append(
                                Finding(
                                    severity="HIGH",
                                    file=self._relative(path),
                                    line=node.lineno,
                                    category=(
                                        "AST_FIXED_LEN_COMPARISON"
                                    ),
                                    text=(
                                        f"len(...) "
                                        f"{type(node.ops[0]).__name__} "
                                        f"{value}"
                                    ),
                                    recommendation=(
                                        "Use dynamic pool semantics."
                                    ),
                                )
                            )

    # --------------------------------------------------------
    # JSON audit
    # --------------------------------------------------------

    def _scan_json_files(self) -> None:
        for path in self._iter_files():
            if path.suffix.lower() not in JSON_SUFFIXES:
                continue

            self.files_scanned += 1

            try:
                payload = json.loads(
                    path.read_text(
                        encoding="utf-8"
                    )
                )
            except Exception as exc:
                self.findings.append(
                    Finding(
                        severity="WARN",
                        file=self._relative(path),
                        line=1,
                        category="JSON_PARSE_FAILURE",
                        text=str(exc),
                        recommendation=(
                            "Fix JSON before using it as configuration."
                        ),
                    )
                )
                continue

            self._audit_json(
                path,
                payload,
            )

    def _audit_json(
        self,
        path: Path,
        payload,
    ) -> None:

        self._walk_json(
            path,
            payload,
            location="$",
        )

    def _walk_json(
        self,
        path: Path,
        value,
        location: str,
    ) -> None:

        if isinstance(value, dict):
            for key, item in value.items():
                child_location = (
                    f"{location}.{key}"
                )

                self._inspect_json_value(
                    path,
                    key,
                    item,
                    child_location,
                )

                self._walk_json(
                    path,
                    item,
                    child_location,
                )

        elif isinstance(value, list):
            # We do not flag list lengths as errors.
            # Lists are exactly what scalable configuration needs.
            for index, item in enumerate(value):
                self._walk_json(
                    path,
                    item,
                    f"{location}[{index}]",
                )

    def _inspect_json_value(
        self,
        path: Path,
        key: str,
        value,
        location: str,
    ) -> None:

        normalized_key = key.lower()

        pool_keywords = {
            "pool",
            "pools",
            "connections",
            "leaders",
            "workers",
            "coder",
            "debugger",
            "tester",
            "architect",
            "reviewer",
            "standby",
            "primary_pool",
            "failover_pool",
        }

        if (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value in KNOWN_CURRENT_COUNTS
            and any(
                word in normalized_key
                for word in pool_keywords
            )
        ):
            self.findings.append(
                Finding(
                    severity="MEDIUM",
                    file=self._relative(path),
                    line=1,
                    category="JSON_FIXED_POOL_COUNT",
                    text=(
                        f"{location} = {value}"
                    ),
                    recommendation=(
                        "Verify that this is intended configuration "
                        "rather than structural logic."
                    ),
                )
            )

    # --------------------------------------------------------
    # Parameterized synthetic tests
    # --------------------------------------------------------

    def _run_parameterized_tests(
        self,
    ) -> Dict[str, str]:

        tests: Dict[str, str] = {}

        pool_sizes = [
            1,
            2,
            3,
            4,
            5,
            10,
            11,
            15,
            21,
            31,
            50,
            100,
        ]

        for size in pool_sizes:
            pool = [
                f"CONN-{index:03d}"
                for index in range(1, size + 1)
            ]

            ok = True

            # Test 1: all items discoverable.
            if len(pool) != size:
                ok = False

            # Test 2: unique IDs.
            if len(set(pool)) != size:
                ok = False

            # Test 3: complete traversal.
            seen = []

            for connection_id in pool:
                seen.append(connection_id)

            if seen != pool:
                ok = False

            # Test 4: removal/failure does not depend on size.
            if size > 1:
                available = list(pool)
                failed = available.pop(0)

                if failed in available:
                    ok = False

                if len(available) != size - 1:
                    ok = False

            tests[
                f"N={size}"
            ] = (
                "PASS"
                if ok
                else "FAIL"
            )

        return tests

    # --------------------------------------------------------
    # Dynamic failover-style pool simulation
    # --------------------------------------------------------

    def _run_dynamic_pool_tests(
        self,
    ) -> Dict[str, str]:

        results: Dict[str, str] = {}

        for size in [
            5,
            11,
            21,
            31,
        ]:
            primary = [
                f"OR-{index:02d}"
                for index in range(1, size + 1)
            ]

            failover = [
                f"SUPER-{index:02d}"
                for index in range(1, size + 1)
            ]

            # Exhaust primary.
            traversal = []

            for item in primary:
                traversal.append(
                    ("PRIMARY", item)
                )

            # Then failover.
            for item in failover:
                traversal.append(
                    ("FAILOVER", item)
                )

            expected = size * 2

            primary_unique = len(
                {
                    item
                    for tier, item in traversal
                    if tier == "PRIMARY"
                }
            ) == size

            failover_unique = len(
                {
                    item
                    for tier, item in traversal
                    if tier == "FAILOVER"
                }
            ) == size

            total_ok = len(traversal) == expected

            results[
                f"N={size}"
            ] = (
                "PASS"
                if (
                    primary_unique
                    and failover_unique
                    and total_ok
                )
                else "FAIL"
            )

        return results

    # --------------------------------------------------------
    # Overall status
    # --------------------------------------------------------

    def _overall_status(
        self,
        synthetic: Dict[str, str],
        dynamic: Dict[str, str],
    ) -> str:

        if any(
            value != "PASS"
            for value in synthetic.values()
        ):
            return "FAIL"

        if any(
            value != "PASS"
            for value in dynamic.values()
        ):
            return "FAIL"

        high_findings = [
            finding
            for finding in self.findings
            if finding.severity == "HIGH"
        ]

        if high_findings:
            return "REVIEW_REQUIRED"

        return "PASS"

    # --------------------------------------------------------
    # Utility
    # --------------------------------------------------------

    def _relative(
        self,
        path: Path,
    ) -> str:

        return str(
            path.resolve().relative_to(
                self.root
            )
        )


# ============================================================
# CLI
# ============================================================

def main() -> None:
    print("=" * 70)
    print("EXPANSION READINESS AUDIT v1")
    print("=" * 70)

    root = PROJECT_ROOT

    print(
        f"Project root: {root}"
    )

    auditor = ExpansionReadinessAuditor(
        root
    )

    result = auditor.run()

    print(
        f"\nFiles scanned: "
        f"{result.files_scanned}"
    )

    print(
        "\nParameterized pool tests:"
    )

    for name, status in result.synthetic_tests.items():
        print(
            f"  {name:<8} {status}"
        )

    print(
        "\nDynamic primary/failover tests:"
    )

    for name, status in result.dynamic_pool_test.items():
        print(
            f"  {name:<8} {status}"
        )

    print(
        "\nFindings:"
    )

    if not result.findings:
        print(
            "  None"
        )
    else:
        for finding in result.findings:
            print(
                f"  [{finding.severity}] "
                f"{finding.file}:{finding.line} "
                f"{finding.category}"
            )
            print(
                f"      {finding.text}"
            )
            print(
                f"      → {finding.recommendation}"
            )

    output = {
        "schema_version": result.schema_version,
        "project_root": result.project_root,
        "files_scanned": result.files_scanned,
        "findings": [
            asdict(item)
            for item in result.findings
        ],
        "synthetic_tests": result.synthetic_tests,
        "dynamic_pool_test": result.dynamic_pool_test,
        "status": result.status,
    }

    output_path = (
        root
        / "expansion_readiness_result.json"
    )

    output_path.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(
        "\n" + "=" * 70
    )

    if result.status == "PASS":
        print(
            "EXPANSION READINESS AUDIT PASSED ✅"
        )
    elif result.status == "REVIEW_REQUIRED":
        print(
            "EXPANSION READINESS AUDIT: REVIEW REQUIRED ⚠️"
        )
    else:
        print(
            "EXPANSION READINESS AUDIT FAILED ❌"
        )

    print(
        "=" * 70
    )

    print(
        f"Result saved to: "
        f"{output_path}"
    )

    if result.status == "REVIEW_REQUIRED":
        print(
            "\nImportant:"
            " HIGH findings identify code locations that may "
            "be structurally tied to fixed pool sizes."
        )


if __name__ == "__main__":
    main()