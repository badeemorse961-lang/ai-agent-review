from __future__ import annotations

from pathlib import Path

from expansion_readiness_audit import ExpansionReadinessAuditor


def _run_python_audit(tmp_path: Path, source: str):
    target = tmp_path / "sample.py"
    target.write_text(source, encoding="utf-8")
    auditor = ExpansionReadinessAuditor(tmp_path)
    auditor._scan_python_files()
    return auditor.findings


def test_cli_argument_length_is_not_pool_finding(tmp_path: Path):
    findings = _run_python_audit(
        tmp_path,
        "import sys\n\n"
        "def main():\n"
        "    if len(sys.argv) == 1:\n"
        "        return 0\n",
    )
    assert findings == []


def test_synthetic_fixed_values_are_ignored(tmp_path: Path):
    findings = _run_python_audit(
        tmp_path,
        "def synthetic_test():\n"
        "    pool = [\"GROQ-01\", \"GROQ-02\"]\n"
        "    return len(pool) == 2\n"
        "\n"
        "def production():\n"
        "    pool = []\n"
        "    return len(pool) == 11\n",
    )
    assert [item.category for item in findings] == ["FIXED_POOL_SIZE_COMPARISON"]
    assert findings[0].line == 7


def test_fixed_pool_range_is_detected_in_production_code(tmp_path: Path):
    findings = _run_python_audit(
        tmp_path,
        "def production(pool):\n"
        "    return [pool[i] for i in range(11)]\n",
    )
    assert len(findings) == 1
    assert findings[0].category == "FIXED_RANGE"


def test_bom_source_is_parsed_without_encoding_warning(tmp_path: Path):
    target = tmp_path / "sample.py"
    target.write_text("\ufeffdef production():\n    return 1\n", encoding="utf-8")

    auditor = ExpansionReadinessAuditor(tmp_path)
    auditor._scan_python_files()

    assert not any(item.category == "SOURCE_DECODE_FAILURE" for item in auditor.findings)
    assert not any(item.category == "AST_PARSE_FAILURE" for item in auditor.findings)
