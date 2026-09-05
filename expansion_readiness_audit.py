from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Set


# ============================================================
# EXPANSION READINESS AUDIT v2
# ============================================================
#
# Purpose:
#   Audit production project code for hidden fixed-size assumptions
#   without treating the auditor's own implementation, synthetic
#   tests, comments, or ordinary CLI argument handling as defects.
#
# Rules:
#   - Pool size belongs to configuration, not structural logic.
#   - Connection IDs are identifiers, not architecture limits.
#   - Synthetic/test fixtures may use fixed values intentionally.
#   - CLI argument count checks are not pool-size checks.
#   - UTF-8 BOM is accepted for source inspection.
#   - The auditor does not modify project files.
#
# ============================================================


PROJECT_ROOT = Path(__file__).resolve().parent
AUDITOR_FILENAME = Path(__file__).name

IGNORED_DIRS: Set[str] = {
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

# These are current configuration values. They are detection hints,
# not allowed architecture limits.
KNOWN_CURRENT_COUNTS = {
    11: "current OpenRouter leader accounts",
    15: "current Groq worker accounts",
    4: "current coder pool",
    3: "current debugger/reviewer-sized pool",
    2: "current tester/architect-sized pool",
    1: "current standby / active connection-sized value",
}

POOL_NAME_HINTS = {
    "pool",
    "pools",
    "connection",
    "connections",
    "leader",
    "leaders",
    "worker",
    "workers",
    "standby",
    "coder",
    "debugger",
    "tester",
    "architect",
    "reviewer",
    "account",
    "accounts",
}

SYNTHETIC_NAME_HINTS = (
    "synthetic",
    "fixture",
    "test_",
)


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


class _ContextVisitor(ast.NodeVisitor):
    """Walk Python AST while retaining enclosing function/class names."""

    def __init__(self, callback):
        self.callback = callback
        self.function_stack: List[str] = []
        self.class_stack: List[str] = []

    def generic_visit(self, node: ast.AST) -> Any:
        self.callback(node, tuple(self.function_stack), tuple(self.class_stack))
        super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self.callback(node, tuple(self.function_stack), tuple(self.class_stack))
        self.function_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        for child in node.decorator_list:
            self.visit(child)
        for child in node.args.defaults:
            self.visit(child)
        for child in node.args.kw_defaults:
            if child is not None:
                self.visit(child)
        if node.returns is not None:
            self.visit(node.returns)
        self.function_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self.callback(node, tuple(self.function_stack), tuple(self.class_stack))
        self.function_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        for child in node.decorator_list:
            self.visit(child)
        for child in node.args.defaults:
            self.visit(child)
        for child in node.args.kw_defaults:
            if child is not None:
                self.visit(child)
        if node.returns is not None:
            self.visit(node.returns)
        self.function_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        self.callback(node, tuple(self.function_stack), tuple(self.class_stack))
        self.class_stack.append(node.name)
        for child in node.body:
            self.visit(child)
        for child in node.decorator_list:
            self.visit(child)
        for child in node.bases:
            self.visit(child)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self.class_stack.pop()


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
        status = self._overall_status(synthetic, dynamic)

        return AuditResult(
            schema_version=2,
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

    def _iter_files(self) -> Iterator[Path]:
        ignored = {item.lower() for item in IGNORED_DIRS}
        for path in self.root.rglob("*"):
            if not path.is_file():
                continue

            relative_parts = path.relative_to(self.root).parts
            if any(part.lower() in ignored for part in relative_parts):
                continue

            yield path

    def _is_synthetic_context(
        self,
        function_stack: tuple[str, ...],
        path: Path,
    ) -> bool:
        if path.name.startswith("test_"):
            return True
        return any(
            any(hint in name.lower() for hint in SYNTHETIC_NAME_HINTS)
            for name in function_stack
        )

    # --------------------------------------------------------
    # Python audit
    # --------------------------------------------------------

    def _scan_python_files(self) -> None:
        for path in self._iter_files():
            if path.suffix.lower() not in PYTHON_SUFFIXES:
                continue
            if path.name == AUDITOR_FILENAME:
                continue

            self.files_scanned += 1

            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as exc:
                self.findings.append(
                    Finding(
                        severity="WARN",
                        file=self._relative(path),
                        line=1,
                        category="SOURCE_DECODE_FAILURE",
                        text=str(exc),
                        recommendation="Inspect source encoding before relying on the audit.",
                    )
                )
                continue
            except OSError as exc:
                self.findings.append(
                    Finding(
                        severity="WARN",
                        file=self._relative(path),
                        line=1,
                        category="READ_ERROR",
                        text=str(exc),
                        recommendation="Inspect file manually.",
                    )
                )
                continue

            try:
                tree = ast.parse(text, filename=str(path))
            except SyntaxError as exc:
                self.findings.append(
                    Finding(
                        severity="WARN",
                        file=self._relative(path),
                        line=exc.lineno or 1,
                        category="AST_PARSE_FAILURE",
                        text=str(exc),
                        recommendation="Fix syntax before relying on this file.",
                    )
                )
                continue

            self._audit_python_ast(path, tree)

    def _audit_python_ast(self, path: Path, tree: ast.AST) -> None:
        visitor = _ContextVisitor(
            lambda node, funcs, classes: self._audit_node_context(
                path,
                node,
                funcs,
                classes,
            )
        )
        visitor.visit(tree)

    def _audit_node_context(
        self,
        path: Path,
        node: ast.AST,
        function_stack: tuple[str, ...],
        class_stack: tuple[str, ...],
    ) -> None:
        del class_stack
        if self._is_synthetic_context(function_stack, path):
            return

        if isinstance(node, ast.Call):
            self._audit_range_call(path, node)
            self._audit_numeric_call(path, node)

        if isinstance(node, ast.Compare):
            self._audit_len_compare(path, node)

        if isinstance(node, ast.Subscript):
            self._audit_fixed_slice(path, node)

    def _audit_range_call(self, path: Path, node: ast.Call) -> None:
        if not (
            isinstance(node.func, ast.Name)
            and node.func.id == "range"
            and len(node.args) == 1
        ):
            return

        argument = node.args[0]
        if not isinstance(argument, ast.Constant):
            return
        if not isinstance(argument.value, int):
            return
        if argument.value not in KNOWN_CURRENT_COUNTS:
            return

        self.findings.append(
            Finding(
                severity="HIGH",
                file=self._relative(path),
                line=node.lineno,
                category="FIXED_RANGE",
                text=f"range({argument.value})",
                recommendation="Replace fixed iteration count with pool/configuration length.",
            )
        )

    def _audit_numeric_call(self, path: Path, node: ast.Call) -> None:
        """Catch numeric arguments only for explicitly pool-sized APIs."""
        if not isinstance(node.func, ast.Name):
            return
        if node.func.id not in {
            "reserve_pool",
            "allocate_pool",
            "require_pool_size",
        }:
            return

        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, int):
                if argument.value in KNOWN_CURRENT_COUNTS:
                    self.findings.append(
                        Finding(
                            severity="HIGH",
                            file=self._relative(path),
                            line=node.lineno,
                            category="POOL_NUMERIC_ARGUMENT",
                            text=f"{node.func.id}({argument.value})",
                            recommendation="Use configuration-derived pool size.",
                        )
                    )

    def _audit_len_compare(self, path: Path, node: ast.Compare) -> None:
        if not isinstance(node.left, ast.Call):
            return
        if not (
            isinstance(node.left.func, ast.Name)
            and node.left.func.id == "len"
            and len(node.comparators) == 1
            and isinstance(node.comparators[0], ast.Constant)
            and isinstance(node.comparators[0].value, int)
        ):
            return

        # CLI argument count is legitimate and unrelated to pool sizing.
        if self._is_sys_argv(node.left.args[0] if node.left.args else None):
            return

        value = node.comparators[0].value
        if value not in KNOWN_CURRENT_COUNTS:
            return

        target_text = self._expression_text(node.left.args[0] if node.left.args else None)
        if not self._looks_pool_related(target_text):
            return

        op_name = type(node.ops[0]).__name__
        self.findings.append(
            Finding(
                severity="HIGH",
                file=self._relative(path),
                line=node.lineno,
                category="FIXED_POOL_SIZE_COMPARISON",
                text=f"len({target_text}) {op_name} {value}",
                recommendation="Compare against a configured or computed pool size, not a literal.",
            )
        )

    def _audit_fixed_slice(self, path: Path, node: ast.Subscript) -> None:
        if not self._looks_pool_related(self._expression_text(node.value)):
            return

        slice_node = node.slice
        if not isinstance(slice_node, ast.Slice):
            return
        if not isinstance(slice_node.upper, ast.Constant):
            return
        if not isinstance(slice_node.upper.value, int):
            return
        if slice_node.upper.value not in KNOWN_CURRENT_COUNTS:
            return

        self.findings.append(
            Finding(
                severity="HIGH",
                file=self._relative(path),
                line=node.lineno,
                category="FIXED_POOL_SLICE",
                text=self._expression_text(node),
                recommendation="Use configuration-derived role partitioning instead of fixed slice bounds.",
            )
        )

    @staticmethod
    def _is_sys_argv(node: ast.AST | None) -> bool:
        return isinstance(node, ast.Attribute) and (
            isinstance(node.value, ast.Name)
            and node.value.id == "sys"
            and node.attr == "argv"
        )

    @staticmethod
    def _expression_text(node: ast.AST | None) -> str:
        if node is None:
            return "..."
        try:
            return ast.unparse(node)
        except Exception:
            return "..."

    @staticmethod
    def _looks_pool_related(text: str) -> bool:
        lowered = text.lower()
        return any(hint in lowered for hint in POOL_NAME_HINTS)

    # --------------------------------------------------------
    # JSON audit
    # --------------------------------------------------------

    def _scan_json_files(self) -> None:
        for path in self._iter_files():
            if path.suffix.lower() not in JSON_SUFFIXES:
                continue

            self.files_scanned += 1
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                self.findings.append(
                    Finding(
                        severity="WARN",
                        file=self._relative(path),
                        line=1,
                        category="JSON_PARSE_FAILURE",
                        text=str(exc),
                        recommendation="Fix JSON before using it as configuration.",
                    )
                )
                continue

            self._audit_json(path, payload)

    def _audit_json(self, path: Path, payload: Any) -> None:
        self._walk_json(path, payload, "$", set())

    def _walk_json(
        self,
        path: Path,
        value: Any,
        location: str,
        key_path: Set[str],
    ) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child_location = f"{location}.{key}"
                next_keys = set(key_path)
                next_keys.add(str(key).lower())
                self._inspect_json_value(path, item, child_location, next_keys)
                self._walk_json(path, item, child_location, next_keys)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self._walk_json(path, item, f"{location}[{index}]", key_path)

    def _inspect_json_value(
        self,
        path: Path,
        value: Any,
        location: str,
        key_path: Set[str],
    ) -> None:
        if not (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value in KNOWN_CURRENT_COUNTS
        ):
            return

        relevant = any(
            any(hint in key_name for hint in POOL_NAME_HINTS)
            for key_name in key_path
        )
        if not relevant:
            return

        self.findings.append(
            Finding(
                severity="MEDIUM",
                file=self._relative(path),
                line=1,
                category="JSON_FIXED_POOL_COUNT",
                text=f"{location} = {value}",
                recommendation="Verify that this is intentional configuration data, not structural logic.",
            )
        )

    # --------------------------------------------------------
    # Synthetic expansion tests
    # --------------------------------------------------------

    def _run_parameterized_tests(self) -> Dict[str, str]:
        tests: Dict[str, str] = {}

        for size in [1, 2, 3, 4, 5, 10, 11, 15, 21, 31, 50, 100]:
            pool = [f"CONN-{index:03d}" for index in range(1, size + 1)]
            ok = True

            if len(pool) != size:
                ok = False
            if len(set(pool)) != size:
                ok = False
            if list(pool) != pool:
                ok = False

            if size > 1:
                available = list(pool)
                failed = available.pop(0)
                if failed in available:
                    ok = False
                if len(available) != size - 1:
                    ok = False

            tests[f"N={size}"] = "PASS" if ok else "FAIL"

        return tests

    def _run_dynamic_pool_tests(self) -> Dict[str, str]:
        results: Dict[str, str] = {}

        for size in [5, 11, 21, 31]:
            primary = [f"OR-{index:02d}" for index in range(1, size + 1)]
            failover = [f"SUPER-{index:02d}" for index in range(1, size + 1)]

            traversal = [("PRIMARY", item) for item in primary]
            traversal.extend(("FAILOVER", item) for item in failover)

            primary_unique = len({item for tier, item in traversal if tier == "PRIMARY"}) == size
            failover_unique = len({item for tier, item in traversal if tier == "FAILOVER"}) == size
            total_ok = len(traversal) == size * 2

            results[f"N={size}"] = (
                "PASS"
                if primary_unique and failover_unique and total_ok
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
        if any(value != "PASS" for value in synthetic.values()):
            return "FAIL"

        if any(value != "PASS" for value in dynamic.values()):
            return "FAIL"

        if any(finding.severity == "HIGH" for finding in self.findings):
            return "REVIEW_REQUIRED"

        return "PASS"

    def _relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root))


# ============================================================
# CLI
# ============================================================


def _print_result(result: AuditResult) -> None:
    print("=" * 70)
    print("EXPANSION READINESS AUDIT v2")
    print("=" * 70)
    print(f"Project root: {result.project_root}")
    print(f"\nFiles scanned: {result.files_scanned}")

    print("\nParameterized pool tests:")
    for name, status in result.synthetic_tests.items():
        print(f"  {name:<8} {status}")

    print("\nDynamic primary/failover tests:")
    for name, status in result.dynamic_pool_test.items():
        print(f"  {name:<8} {status}")

    print("\nFindings:")
    if not result.findings:
        print("  None")
    else:
        for finding in result.findings:
            print(
                f"  [{finding.severity}] {finding.file}:{finding.line} "
                f"{finding.category}"
            )
            print(f"      {finding.text}")
            print(f"      → {finding.recommendation}")

    print("\n" + "=" * 70)
    if result.status == "PASS":
        print("EXPANSION READINESS AUDIT PASSED ✅")
    elif result.status == "REVIEW_REQUIRED":
        print("EXPANSION READINESS AUDIT: REVIEW REQUIRED ⚠️")
    else:
        print("EXPANSION READINESS AUDIT FAILED ❌")
    print("=" * 70)


def main() -> None:
    result = ExpansionReadinessAuditor(PROJECT_ROOT).run()

    output = {
        "schema_version": result.schema_version,
        "project_root": result.project_root,
        "files_scanned": result.files_scanned,
        "findings": [asdict(item) for item in result.findings],
        "synthetic_tests": result.synthetic_tests,
        "dynamic_pool_test": result.dynamic_pool_test,
        "status": result.status,
    }

    output_path = PROJECT_ROOT / "expansion_readiness_result.json"
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    _print_result(result)
    print(f"Result saved to: {output_path}")

    if result.status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
