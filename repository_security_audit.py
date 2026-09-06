from __future__ import annotations

import ast
import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PRODUCTION_SUBPROCESS_ALLOWLIST = {"process_sandbox.py"}
FORBIDDEN_SUBPROCESS_APIS = {"run", "Popen", "call", "check_call", "check_output"}
FORBIDDEN_OS_APIS = {"system", "popen"}
SECRET_PATTERNS = (
    re.compile(r"\bgsk_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsk-or-v1-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+\-/=]{12,}\b"),
)
PROTECTED_LOCAL_NAMES = {
    "groq_keys.txt",
    "openrouter_keys.txt",
    "groq_keys.backup.txt",
    "openrouter_keys.backup.txt",
}


@dataclass(frozen=True)
class AuditFinding:
    rule: str
    path: str
    detail: str


class RepositorySecurityAuditError(RuntimeError):
    """Base error for security-audit failures."""


def _python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if any(part in {".git", ".venv", "venv", "__pycache__"} for part in path.parts):
            continue
        yield path


def _production_python_files(root: Path) -> Iterable[Path]:
    for path in _python_files(root):
        if not path.name.startswith("test_"):
            yield path


def _literal_bool_keyword(node: ast.Call, name: str, expected: bool) -> bool:
    for keyword in node.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value is expected
    return False


def _import_aliases(tree: ast.AST) -> tuple[set[str], set[str], set[str], set[str]]:
    subprocess_modules: set[str] = {"subprocess"}
    os_modules: set[str] = {"os"}
    subprocess_functions: set[str] = set()
    os_functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    subprocess_modules.add(alias.asname or alias.name)
                elif alias.name == "os":
                    os_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "subprocess":
                for alias in node.names:
                    if alias.name in FORBIDDEN_SUBPROCESS_APIS:
                        subprocess_functions.add(alias.asname or alias.name)
            elif node.module == "os":
                for alias in node.names:
                    if alias.name in FORBIDDEN_OS_APIS:
                        os_functions.add(alias.asname or alias.name)
    return subprocess_modules, os_modules, subprocess_functions, os_functions


def audit_python_execution_boundaries(root: Path) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for path in _production_python_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (UnicodeDecodeError, SyntaxError) as exc:
            findings.append(AuditFinding("parseable-source", relative, str(exc)))
            continue

        subprocess_modules, os_modules, subprocess_functions, os_functions = _import_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                owner = node.func.value.id
                method = node.func.attr
                if owner in subprocess_modules and method in FORBIDDEN_SUBPROCESS_APIS:
                    if relative not in PRODUCTION_SUBPROCESS_ALLOWLIST:
                        findings.append(
                            AuditFinding(
                                "subprocess-boundary",
                                relative,
                                f"direct subprocess.{method} call is outside ProcessSandbox",
                            )
                        )
                if owner in os_modules and method in FORBIDDEN_OS_APIS:
                    findings.append(
                        AuditFinding(
                            "shell-execution",
                            relative,
                            f"forbidden os.{method} primitive",
                        )
                    )
                if owner in subprocess_modules and _literal_bool_keyword(node, "shell", True):
                    findings.append(
                        AuditFinding(
                            "shell-execution",
                            relative,
                            "subprocess call enables shell=True",
                        )
                    )

            if isinstance(node.func, ast.Name):
                if node.func.id in subprocess_functions and relative not in PRODUCTION_SUBPROCESS_ALLOWLIST:
                    findings.append(
                        AuditFinding(
                            "subprocess-boundary",
                            relative,
                            f"imported subprocess.{node.func.id} call is outside ProcessSandbox",
                        )
                    )
                if node.func.id in os_functions:
                    findings.append(
                        AuditFinding(
                            "shell-execution",
                            relative,
                            f"forbidden imported os.{node.func.id} primitive",
                        )
                    )
    return findings


def audit_protected_local_names(root: Path) -> list[AuditFinding]:
    gitignore = root / ".gitignore"
    if not gitignore.is_file():
        return [AuditFinding("protected-local-state", ".gitignore", "missing .gitignore")]
    patterns = [
        line.strip()
        for line in gitignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    findings: list[AuditFinding] = []
    for name in sorted(PROTECTED_LOCAL_NAMES):
        covered = any(
            fnmatch.fnmatch(name, pattern)
            or fnmatch.fnmatch(name, pattern.lstrip("/"))
            or fnmatch.fnmatch(f"**/{name}", pattern)
            for pattern in patterns
        )
        if not covered:
            findings.append(
                AuditFinding(
                    "protected-local-state",
                    ".gitignore",
                    f"protected local filename is not ignored: {name}",
                )
            )
    return findings


def audit_no_credential_literals(root: Path) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for path in _production_python_files(root):
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8", errors="strict")
        for pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                findings.append(
                    AuditFinding(
                        "credential-literal",
                        relative,
                        f"credential-shaped literal detected at offset {match.start()}",
                    )
                )
                break
    return findings


def run_audit(root: Path) -> tuple[AuditFinding, ...]:
    root = root.resolve()
    findings: list[AuditFinding] = []
    findings.extend(audit_python_execution_boundaries(root))
    findings.extend(audit_protected_local_names(root))
    findings.extend(audit_no_credential_literals(root))
    return tuple(findings)


def main() -> int:
    findings = run_audit(Path(__file__).resolve().parent)
    if findings:
        for finding in findings:
            print(f"FAIL [{finding.rule}] {finding.path}: {finding.detail}")
        return 1
    print("REPOSITORY SECURITY AUDIT PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
