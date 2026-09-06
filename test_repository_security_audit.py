from __future__ import annotations

from pathlib import Path

from repository_security_audit import (
    audit_no_credential_literals,
    audit_protected_local_names,
    audit_python_execution_boundaries,
    run_audit,
)


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_current_repository_audit_is_clean() -> None:
    root = Path(__file__).resolve().parent
    assert run_audit(root) == ()


def test_direct_subprocess_call_is_rejected_outside_process_sandbox(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "\n".join([
        "groq_keys.txt",
        "openrouter_keys.txt",
        "groq_keys.backup.txt",
        "openrouter_keys.backup.txt",
    ]))
    write(tmp_path, "unsafe.py", "import subprocess\nsubprocess.run([\"echo\", \"x\"])\n")

    findings = audit_python_execution_boundaries(tmp_path)

    assert any(
        finding.rule == "subprocess-boundary" and finding.path == "unsafe.py"
        for finding in findings
    )


def test_subprocess_alias_and_from_import_are_rejected(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "groq_keys.txt\nopenrouter_keys.txt\ngroq_keys.backup.txt\nopenrouter_keys.backup.txt\n")
    write(
        tmp_path,
        "unsafe.py",
        "import subprocess as sp\nfrom subprocess import run as execute\nsp.run([\"echo\"])\nexecute([\"echo\"])\n",
    )

    findings = audit_python_execution_boundaries(tmp_path)

    assert sum(finding.rule == "subprocess-boundary" for finding in findings) == 2


def test_shell_true_and_os_alias_are_rejected(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "groq_keys.txt\nopenrouter_keys.txt\ngroq_keys.backup.txt\nopenrouter_keys.backup.txt\n")
    write(
        tmp_path,
        "unsafe.py",
        "import os as operating_system\nfrom os import popen as open_pipe\nimport subprocess\nsubprocess.run([\"echo\"], shell=True)\noperating_system.system(\"echo\")\nopen_pipe(\"echo\")\n",
    )

    findings = audit_python_execution_boundaries(tmp_path)

    assert sum(finding.rule == "shell-execution" for finding in findings) == 3


def test_protected_local_names_must_be_ignored(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "groq_keys.txt\nopenrouter_keys.txt\n")

    findings = audit_protected_local_names(tmp_path)

    assert [finding.detail for finding in findings] == [
        "protected local filename is not ignored: groq_keys.backup.txt",
        "protected local filename is not ignored: openrouter_keys.backup.txt",
    ]


def test_credential_shaped_literal_is_rejected(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "groq_keys.txt\nopenrouter_keys.txt\ngroq_keys.backup.txt\nopenrouter_keys.backup.txt\n")
    fake = "gsk_" + "A" * 20
    write(tmp_path, "credential.py", f"TOKEN = {fake!r}\n")

    findings = audit_no_credential_literals(tmp_path)

    assert len(findings) == 1
    assert findings[0].rule == "credential-literal"
    assert findings[0].path == "credential.py"


def test_test_files_do_not_bypass_execution_boundary_rule(tmp_path: Path) -> None:
    write(tmp_path, ".gitignore", "groq_keys.txt\nopenrouter_keys.txt\ngroq_keys.backup.txt\nopenrouter_keys.backup.txt\n")
    write(tmp_path, "test_fixture.py", "import subprocess\nsubprocess.run([\"echo\", \"x\"])\n")

    findings = audit_python_execution_boundaries(tmp_path)

    assert findings == []
