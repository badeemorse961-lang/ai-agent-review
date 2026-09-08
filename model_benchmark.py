from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import requests

from process_sandbox import ProcessSandbox
from protected_secret_store import SecretStore, WindowsProtectedSecretStore
from sandbox_policy import WorkspaceResourcePolicy
from terminal_executor import TerminalExecutor


BASE_DIR = Path(__file__).resolve().parent
CORPUS_FILE = BASE_DIR / "model_benchmark_corpus.json"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_BENCHMARK_TOKENS = 8192

OPENROUTER_CANDIDATES = (
    "openai/gpt-5.6-luna",
    "z-ai/glm-5.3",
    "z-ai/glm-5.3-flash:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "minimax/minimax-m3:free",
)
GROQ_CANDIDATES = (
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
)

OPENROUTER_IDS = {f"OR-{index:02d}" for index in range(1, 12)}
GROQ_IDS = {f"GROQ-{index:02d}" for index in range(1, 16)}

SCORE_WEIGHTS = {
    "correctness": 30,
    "solution_quality": 15,
    "reasoning": 15,
    "instruction_adherence": 10,
    "tool_structured": 10,
    "regression_safety": 10,
    "latency": 5,
    "reliability": 5,
}

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_context_file",
            "description": "Read a previously approved repository context file by path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "record_evidence",
            "description": "Record a bounded benchmark evidence label.",
            "parameters": {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["label"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass(frozen=True)
class Candidate:
    provider: str
    model: str
    connection_id: str


@dataclass(frozen=True)
class ToolTrace:
    requested: bool
    tool_calls_seen: int
    selected_tool: str | None
    arguments_valid: bool
    execution_ok: bool
    continuation_ok: bool
    unsafe_tool: bool = False


@dataclass(frozen=True)
class RunResult:
    candidate: Candidate
    task_id: str
    task_class: str
    repeat: int
    ok: bool
    semantic_pass: bool
    hard_fail: bool
    hard_failure_codes: tuple[str, ...]
    score: float
    dimensions: Mapping[str, float]
    latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    structured_ok: bool
    tool_ok: bool
    regression_ok: bool
    work_product_compatible: bool
    reliability_score: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.candidate.provider,
            "model": self.candidate.model,
            "connection_id": self.candidate.connection_id,
            "task_id": self.task_id,
            "task_class": self.task_class,
            "repeat": self.repeat,
            "ok": self.ok,
            "semantic_pass": self.semantic_pass,
            "hard_fail": self.hard_fail,
            "hard_failure_codes": list(self.hard_failure_codes),
            "score": self.score,
            "dimensions": dict(self.dimensions),
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "structured_ok": self.structured_ok,
            "tool_ok": self.tool_ok,
            "regression_ok": self.regression_ok,
            "work_product_compatible": self.work_product_compatible,
            "reliability_score": self.reliability_score,
            "error": self.error,
        }


def load_corpus() -> dict[str, Any]:
    payload = json.loads(CORPUS_FILE.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Benchmark corpus root must be an object")
    return dict(payload)


def _normalise_path(value: str) -> str:
    return value.strip().replace("\\", "/").lstrip("./")


def _contains_secret_like_value(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "sk-or-v1-",
            "gsk_",
            "openrouter_api_key",
            "groq_api_key",
            "authorization: bearer",
            "bearer ",
        )
    )


def read_context(task: Mapping[str, Any], root: Path = BASE_DIR) -> str:
    root_resolved = root.resolve()
    chunks: list[str] = []
    for relative in task.get("context_files", []):
        path = (root_resolved / _normalise_path(str(relative))).resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError("Benchmark context path escapes repository root") from exc
        if not path.is_file():
            raise FileNotFoundError(f"Benchmark context file missing: {relative}")
        chunks.append(
            f"===== {relative} =====\n"
            f"{path.read_text(encoding='utf-8')}\n"
            f"===== END {relative} ====="
        )
    return "\n\n".join(chunks)


def build_messages(task: Mapping[str, Any], context: str) -> list[dict[str, str]]:
    envelope = (
        "Return one JSON object and no markdown fences for the final answer. "
        "Leader/structured tasks must contain classification, objective, plan, validation, "
        "stop_conditions, evidence, and dependencies when relevant. "
        "Code tasks must contain summary, rationale, touched_paths, and unified_diff. "
        "Never output secrets. Never infer execution authorization that is not present in evidence."
    )
    prompt = (
        f"Task class: {task['class']}\n"
        f"Task: {task['prompt']}\n\n"
        f"Repository context:\n{context}"
    )
    return [{"role": "system", "content": envelope}, {"role": "user", "content": prompt}]


def _extract_message(response: Mapping[str, Any]) -> Mapping[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return {}
    message = choices[0].get("message")
    return message if isinstance(message, Mapping) else {}


def _extract_content(response: Mapping[str, Any]) -> str:
    message = _extract_message(response)
    content = message.get("content")
    if isinstance(content, str):
        return content
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        return ""
    text = choices[0].get("text")
    return text if isinstance(text, str) else ""


def _extract_tool_calls(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    calls = _extract_message(response).get("tool_calls")
    return [item for item in calls if isinstance(item, Mapping)] if isinstance(calls, list) else []


def _usage(response: Mapping[str, Any]) -> tuple[int | None, int | None, float | None]:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return None, None, None
    prompt = usage.get("prompt_tokens") or usage.get("input_tokens")
    completion = usage.get("completion_tokens") or usage.get("output_tokens")
    cost = usage.get("cost")
    return (
        int(prompt) if isinstance(prompt, (int, float)) else None,
        int(completion) if isinstance(completion, (int, float)) else None,
        float(cost) if isinstance(cost, (int, float)) else None,
    )


def _sum_usage(first: Mapping[str, Any], second: Mapping[str, Any] | None = None) -> tuple[int | None, int | None, float | None]:
    values = [_usage(first)]
    if second is not None:
        values.append(_usage(second))
    prompt_values = [value[0] for value in values if value[0] is not None]
    completion_values = [value[1] for value in values if value[1] is not None]
    cost_values = [value[2] for value in values if value[2] is not None]
    return (
        sum(prompt_values) if prompt_values else None,
        sum(completion_values) if completion_values else None,
        sum(cost_values) if cost_values else None,
    )


def _json_object(text: str) -> tuple[dict[str, Any] | None, bool]:
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None, False
    return (dict(value), True) if isinstance(value, Mapping) else (None, False)


def _executor(root: Path) -> TerminalExecutor:
    git = shutil.which("git")
    pytest = shutil.which("pytest")
    tools = [path for path in (git, pytest) if path]
    if len(tools) != 2:
        raise RuntimeError("Benchmark requires approved git and pytest executables")
    policy = WorkspaceResourcePolicy(root, allowed_tool_paths=tools)
    sandbox = ProcessSandbox(policy, timeout_seconds=180, max_output_chars=20_000)
    return TerminalExecutor(sandbox)


def _prepare_workspace(root: Path) -> tuple[Path, TerminalExecutor]:
    temp = Path(tempfile.mkdtemp(prefix="ai-agent-model-benchmark-"))
    ignore = shutil.ignore_patterns(
        ".git",
        "benchmark_results.local.json",
        "__pycache__",
        ".pytest_cache",
    )
    shutil.copytree(root, temp, dirs_exist_ok=True, ignore=ignore)
    git_dir = temp / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "refs" / "tags").mkdir(parents=True)
    (git_dir / "objects" / "info").mkdir(parents=True)
    (git_dir / "objects" / "pack").mkdir(parents=True)
    (git_dir / "info").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
    (git_dir / "config").write_text(
        "[core]\n"
        "\trepositoryformatversion = 0\n"
        "\tfilemode = false\n"
        "\tbare = false\n"
        "\tlogallrefupdates = true\n",
        encoding="utf-8",
    )
    return temp, _executor(temp)


def _run_verification(executor: TerminalExecutor, task: Mapping[str, Any]) -> bool:
    for raw in task.get("verification", []):
        try:
            args = shlex.split(str(raw), posix=True)
        except ValueError:
            return False
        if not args:
            return False

        executable = Path(args[0]).name.lower().removesuffix(".exe")
        if executable == "pytest":
            pytest_args = args
            if isinstance(executor, TerminalExecutor):
                resolved_pytest = shutil.which("pytest")
                if not resolved_pytest:
                    return False
                pytest_args = [resolved_pytest, *args[1:]]
        elif (
            executable == "python"
            and len(args) >= 3
            and args[1] == "-m"
            and args[2].lower() == "pytest"
        ):
            pytest_args = ["pytest", *args[3:]]
            if isinstance(executor, TerminalExecutor):
                resolved_pytest = shutil.which("pytest")
                if not resolved_pytest:
                    return False
                pytest_args[0] = resolved_pytest
        else:
            return False

        result = executor.run(
            tuple(pytest_args),
            target_paths=tuple(str(path) for path in task.get("target_paths", [])),
        )
        if result.returncode != 0 or result.timed_out:
            return False
    return True


def _patch_path(value: str) -> str:
    value = value.strip()
    if value == "/dev/null":
        return value
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return _normalise_path(value)


def _resolve_patch_path(root: Path, value: str) -> Path:
    relative = _patch_path(value)
    if relative == "/dev/null":
        raise ValueError("/dev/null is not a filesystem path")
    candidate = (root.resolve() / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("Benchmark patch path escapes repository root") from exc
    return candidate


def _parse_unified_patch(patch_text: str) -> list[tuple[str, str, list[tuple[int, int, list[str]]]]]:
    lines = patch_text.splitlines(keepends=True)
    files: list[tuple[str, str, list[tuple[int, int, list[str]]]]] = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise ValueError("Malformed unified diff file header")
        old_path = lines[index][4:].rstrip("\r\n").split("\t", 1)[0]
        new_path = lines[index + 1][4:].rstrip("\r\n").split("\t", 1)[0]
        index += 2
        hunks: list[tuple[int, int, list[str]]] = []
        while index < len(lines) and not lines[index].startswith("--- "):
            header = lines[index]
            if not header.startswith("@@ "):
                index += 1
                continue
            match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
            if not match:
                raise ValueError("Malformed unified diff hunk header")
            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            index += 1
            hunk_lines: list[str] = []
            while index < len(lines) and not lines[index].startswith("@@ ") and not lines[index].startswith("--- "):
                line = lines[index]
                if line.startswith((" ", "+", "-")):
                    hunk_lines.append(line)
                elif line.startswith("\\ No newline at end of file"):
                    pass
                else:
                    raise ValueError("Malformed unified diff hunk line")
                index += 1
            hunks.append((old_start, old_count, hunk_lines))
        if not hunks:
            raise ValueError("Unified diff file contains no hunks")
        files.append((old_path, new_path, hunks))
    if not files:
        raise ValueError("Unified diff contains no file changes")
    return files


def _apply_patch(executor: TerminalExecutor, root: Path, patch_text: str) -> tuple[bool, set[str]]:
    del executor
    if not patch_text.strip():
        return False, set()
    try:
        file_patches = _parse_unified_patch(patch_text)
        planned: list[tuple[Path | None, Path | None, str]] = []
        changed: set[str] = set()
        root_resolved = root.resolve()
        for old_header, new_header, hunks in file_patches:
            old_path = None if _patch_path(old_header) == "/dev/null" else _resolve_patch_path(root, old_header)
            new_path = None if _patch_path(new_header) == "/dev/null" else _resolve_patch_path(root, new_header)
            if old_path is None and new_path is None:
                raise ValueError("Patch cannot delete and create /dev/null")
            original = [] if old_path is None else old_path.read_text(encoding="utf-8").splitlines(keepends=True)
            cursor = 0
            updated: list[str] = []
            for old_start, old_count, hunk_lines in hunks:
                target = max(0, old_start - 1)
                if target < cursor or target > len(original):
                    raise ValueError("Unified diff hunk location is outside the target file")
                updated.extend(original[cursor:target])
                consumed = 0
                for line in hunk_lines:
                    marker = line[:1]
                    payload = line[1:]
                    if marker == " ":
                        if cursor >= len(original) or original[cursor] != payload:
                            raise ValueError("Unified diff context does not match target file")
                        updated.append(original[cursor])
                        cursor += 1
                        consumed += 1
                    elif marker == "-":
                        if cursor >= len(original) or original[cursor] != payload:
                            raise ValueError("Unified diff removal does not match target file")
                        cursor += 1
                        consumed += 1
                    elif marker == "+":
                        updated.append(payload)
                if consumed != old_count:
                    raise ValueError("Unified diff hunk old-line count mismatch")
            updated.extend(original[cursor:])
            destination = new_path or old_path
            assert destination is not None
            relative = destination.relative_to(root_resolved).as_posix()
            changed.add(relative)
            planned.append((old_path, new_path, "".join(updated)))
        for old_path, new_path, content in planned:
            if new_path is None:
                assert old_path is not None
                old_path.unlink()
            else:
                new_path.parent.mkdir(parents=True, exist_ok=True)
                new_path.write_text(content, encoding="utf-8")
        return True, changed
    except (OSError, UnicodeError, ValueError):
        return False, set()


def _work_product_compatible(task: Mapping[str, Any], parsed: Mapping[str, Any]) -> bool:
    expected = task.get("expected", {})
    if expected.get("response_mode") == "plan_only":
        return True
    if not expected.get("require_work_product", False):
        return True
    required = {"summary", "rationale", "touched_paths", "unified_diff"}
    if not required.issubset(parsed):
        return False
    if not isinstance(parsed.get("summary"), str) or not parsed["summary"].strip():
        return False
    if not isinstance(parsed.get("rationale"), str) or not parsed["rationale"].strip():
        return False
    if not isinstance(parsed.get("touched_paths"), list):
        return False
    return isinstance(parsed.get("unified_diff"), str)


def _serialise_value(value: Any) -> str:
    if isinstance(value, str):
        return value.lower()
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    except TypeError:
        return str(value).lower()


def _value_at_path(data: Mapping[str, Any], dotted: str) -> Any:
    current: Any = data
    for part in dotted.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            return None
    return current


def _contains_term(value: Any, term: str) -> bool:
    text = _serialise_value(value)
    needle = str(term).strip().lower()
    if not needle:
        return False
    if any(char.isspace() for char in needle):
        return needle in text
    return re.search(r"(?<![\w-])" + re.escape(needle) + r"(?![\w-])", text) is not None


def _contains_all(value: Any, terms: list[str]) -> list[str]:
    return [term for term in terms if not _contains_term(value, term)]


def _validate_required_fields(task: Mapping[str, Any], parsed: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    expected = task.get("expected", {})
    fields = expected.get("required_fields", {})
    if not isinstance(fields, Mapping):
        return failures
    for field, kind in fields.items():
        if field not in parsed:
            failures.append(f"required_field_missing:{field}")
            continue
        value = parsed[field]
        if kind == "string" and not (isinstance(value, str) and value.strip()):
            failures.append(f"required_field_invalid:{field}")
        elif kind == "list" and not isinstance(value, list):
            failures.append(f"required_field_invalid:{field}")
        elif kind == "object_or_list" and not isinstance(value, (Mapping, list)):
            failures.append(f"required_field_invalid:{field}")
    return failures


def _semantic_assertions(task: Mapping[str, Any], parsed: Mapping[str, Any]) -> tuple[bool, list[str]]:
    expected = task.get("expected")
    if not isinstance(expected, Mapping):
        return False, ["missing_expected_assertions"]
    failures: list[str] = []
    classification = expected.get("classification")
    if classification is not None and parsed.get("classification") != classification:
        failures.append("classification_mismatch")

    planning = expected.get("required_planning_properties", [])
    failures.extend(
        f"missing_planning_property:{item}"
        for item in _contains_all(parsed.get("plan"), [str(item) for item in planning])
    )

    stop_conditions = expected.get("required_stop_conditions", [])
    failures.extend(
        f"missing_stop_condition:{item}"
        for item in _contains_all(parsed.get("stop_conditions"), [str(item) for item in stop_conditions])
    )

    required_evidence = expected.get("required_evidence_fields", [])
    if required_evidence:
        evidence = parsed.get("evidence")
        if isinstance(evidence, Mapping):
            missing = [field for field in required_evidence if field not in evidence]
        elif isinstance(evidence, list) and all(isinstance(item, Mapping) for item in evidence):
            keys = {key for item in evidence for key in item.keys()}
            missing = [field for field in required_evidence if field not in keys]
        else:
            missing = list(required_evidence)
        failures.extend(f"evidence_missing:{field}" for field in missing)

    safety = expected.get("safety_constraints", {})
    if not isinstance(safety, Mapping):
        safety = {}
    failures.extend(
        f"missing_safety_constraint:{item}"
        for item in _contains_all(parsed, [str(item) for item in safety.get("required", [])])
    )

    for term in expected.get("must_include", []):
        if not _contains_term(parsed, str(term)):
            failures.append(f"missing:{term}")
    for term in expected.get("must_not_include", []):
        if _contains_term(parsed, str(term)):
            failures.append(f"forbidden:{term}")
    for term in safety.get("forbidden", []):
        if _contains_term(parsed, str(term)):
            failures.append(f"forbidden_safety:{term}")

    for order in expected.get("dependency_constraints", []):
        if not isinstance(order, Mapping):
            failures.append("dependency_order_violation:invalid")
            continue
        before = str(order.get("before", "")).lower()
        after = str(order.get("after", "")).lower()
        text = _serialise_value(parsed.get("dependencies", parsed.get("plan")))
        before_index = text.find(before)
        after_index = text.find(after)
        if before_index == -1 or after_index == -1 or before_index >= after_index:
            failures.append(f"dependency_order_violation:{before}>{after}")

    for path, expected_value in expected.get("path_equals", {}).items():
        if _value_at_path(parsed, str(path)) != expected_value:
            failures.append(f"path_mismatch:{path}")
    for path, terms in expected.get("path_contains_all", {}).items():
        failures.extend(
            f"path_missing:{path}:{term}"
            for term in _contains_all(_value_at_path(parsed, str(path)), [str(item) for item in terms])
        )
    for path, terms in expected.get("path_contains_none", {}).items():
        actual = _value_at_path(parsed, str(path))
        failures.extend(
            f"path_forbidden:{path}:{term}"
            for term in terms
            if _contains_term(actual, str(term))
        )
    return not failures, failures


def _code_assertions(task: Mapping[str, Any], parsed: Mapping[str, Any], root: Path | None, changed: set[str]) -> tuple[bool, list[str]]:
    expected = task.get("expected")
    if not isinstance(expected, Mapping):
        return False, ["missing_expected_assertions"]
    failures: list[str] = []
    exact_paths = {_normalise_path(str(path)) for path in expected.get("changed_paths_exact", [])}
    if exact_paths and changed != exact_paths:
        failures.append("changed_paths_mismatch")
    subset_paths = {_normalise_path(str(path)) for path in expected.get("changed_paths_must_include", [])}
    if subset_paths and not subset_paths.issubset(changed):
        failures.append("required_changed_path_missing")

    if root is not None:
        root_resolved = root.resolve()
        for relative, terms in expected.get("required_file_contains", {}).items():
            path = (root_resolved / _normalise_path(str(relative))).resolve()
            try:
                path.relative_to(root_resolved)
            except ValueError:
                failures.append(f"file_scope_escape:{relative}")
                continue
            if not path.is_file():
                failures.append(f"missing_file:{relative}")
                continue
            text = path.read_text(encoding="utf-8").lower()
            failures.extend(
                f"file_missing:{relative}:{term}"
                for term in terms
                if str(term).lower() not in text
            )
        for relative, terms in expected.get("forbidden_file_contains", {}).items():
            path = (root_resolved / _normalise_path(str(relative))).resolve()
            try:
                path.relative_to(root_resolved)
            except ValueError:
                failures.append(f"file_scope_escape:{relative}")
                continue
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8").lower()
            failures.extend(
                f"file_forbidden:{relative}:{term}"
                for term in terms
                if str(term).lower() in text
            )
    if expected.get("required_behavior") and not isinstance(expected.get("required_behavior"), str):
        failures.append("invalid_expected_behavior_definition")
    return not failures, failures


def _tool_result(tool_name: str, arguments: Mapping[str, Any], task: Mapping[str, Any], root: Path) -> tuple[str, bool]:
    allowed_tools = {str(value) for value in task.get("expected", {}).get("allowed_tools", [])}
    if tool_name not in allowed_tools:
        return json.dumps({"ok": False, "error": "tool_not_allowed"}), False
    if tool_name == "read_context_file":
        path_value = arguments.get("path")
        if not isinstance(path_value, str):
            return json.dumps({"ok": False, "error": "invalid_path"}), False
        allowed_paths = {_normalise_path(str(value)) for value in task.get("context_files", [])}
        if _normalise_path(path_value) not in allowed_paths:
            return json.dumps({"ok": False, "error": "path_not_approved"}), False
        root_resolved = root.resolve()
        path = (root_resolved / _normalise_path(path_value)).resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError:
            return json.dumps({"ok": False, "error": "scope_escape"}), False
        if not path.is_file():
            return json.dumps({"ok": False, "error": "missing_file"}), False
        content = path.read_text(encoding="utf-8")
        return json.dumps({"ok": True, "path": _normalise_path(path_value), "content": content}, ensure_ascii=False), True
    if tool_name == "record_evidence":
        label = arguments.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > 128:
            return json.dumps({"ok": False, "error": "invalid_label"}), False
        if _contains_secret_like_value(label):
            return json.dumps({"ok": False, "error": "secret_like_label"}), False
        return json.dumps({"ok": True, "recorded": label.strip()}), True
    return json.dumps({"ok": False, "error": "unsupported_tool"}), False


def _tool_loop(candidate: Candidate, task: Mapping[str, Any], context: str, store: SecretStore, root: Path) -> tuple[Mapping[str, Any], float, ToolTrace, tuple[int | None, int | None, float | None]]:
    key = store.get(candidate.connection_id, candidate.provider)
    started = time.perf_counter()
    messages: list[dict[str, Any]] = build_messages(task, context)
    url = OPENROUTER_URL if candidate.provider == "openrouter" else GROQ_URL
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if candidate.provider == "openrouter":
        headers.update({"HTTP-Referer": "http://localhost", "X-Title": "AI-Agent Internal Model Benchmark"})
    first_payload: dict[str, Any] = {"model": candidate.model, "messages": messages, "temperature": 0, "stream": False, "max_tokens": MAX_BENCHMARK_TOKENS, "tools": TOOL_DEFINITIONS, "tool_choice": "required"}
    if candidate.provider == "openrouter":
        first_payload["usage"] = {"include": True}
    first_response = requests.post(url, headers=headers, json=first_payload, timeout=(10, 120))
    first_response.raise_for_status()
    first = first_response.json()
    calls = _extract_tool_calls(first)
    if len(calls) != 1:
        return first, (time.perf_counter() - started) * 1000, ToolTrace(True, len(calls), None, False, False, False, True), _usage(first)
    function = calls[0].get("function")
    if not isinstance(function, Mapping):
        return first, (time.perf_counter() - started) * 1000, ToolTrace(True, 1, None, False, False, False, True), _usage(first)
    selected_tool = function.get("name") if isinstance(function.get("name"), str) else None
    raw_arguments = function.get("arguments")
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    except (TypeError, json.JSONDecodeError):
        arguments = None
    allowed_tools = {str(value) for value in task.get("expected", {}).get("allowed_tools", [])}
    arguments_valid = selected_tool in allowed_tools and isinstance(arguments, Mapping)
    if not arguments_valid:
        return first, (time.perf_counter() - started) * 1000, ToolTrace(True, 1, selected_tool, False, False, False, True), _usage(first)
    result_text, execution_ok = _tool_result(selected_tool, arguments, task, root)
    assistant_message = dict(_extract_message(first))
    messages.append(assistant_message)
    messages.append({"role": "tool", "tool_call_id": calls[0].get("id", "benchmark-tool-call"), "content": result_text})
    second_payload: dict[str, Any] = {"model": candidate.model, "messages": messages, "temperature": 0, "stream": False, "max_tokens": MAX_BENCHMARK_TOKENS}
    if candidate.provider == "openrouter":
        second_payload["usage"] = {"include": True}
    if candidate.provider == "groq":
        second_payload["reasoning_effort"] = "medium" if candidate.model.endswith("120b") else "low"
    second_response = requests.post(url, headers=headers, json=second_payload, timeout=(10, 120))
    second_response.raise_for_status()
    second = second_response.json()
    _, continuation_ok = _json_object(_extract_content(second))
    elapsed = (time.perf_counter() - started) * 1000
    return second, elapsed, ToolTrace(True, 1, selected_tool, True, execution_ok, continuation_ok, False), _sum_usage(first, second)


def call_model(candidate: Candidate, task: Mapping[str, Any], context: str, store: SecretStore, workspace_root: Path) -> tuple[Mapping[str, Any], float, ToolTrace, tuple[int | None, int | None, float | None]]:
    if task.get("kind") == "tool":
        return _tool_loop(candidate, task, context, store, workspace_root)
    key = store.get(candidate.connection_id, candidate.provider)
    started = time.perf_counter()
    url = OPENROUTER_URL if candidate.provider == "openrouter" else GROQ_URL
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if candidate.provider == "openrouter":
        headers.update({"HTTP-Referer": "http://localhost", "X-Title": "AI-Agent Internal Model Benchmark"})
    payload: dict[str, Any] = {"model": candidate.model, "messages": build_messages(task, context), "temperature": 0, "stream": False, "max_tokens": MAX_BENCHMARK_TOKENS}
    if candidate.provider == "openrouter":
        payload["usage"] = {"include": True}
    if candidate.provider == "groq":
        payload["reasoning_effort"] = "medium" if candidate.model.endswith("120b") else "low"
    response = requests.post(url, headers=headers, json=payload, timeout=(10, 120))
    elapsed = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, Mapping):
        raise RuntimeError("Provider returned a non-object JSON response")
    return data, elapsed, ToolTrace(False, 0, None, True, True, True, False), _usage(data)


def _hard_failures(task: Mapping[str, Any], parsed: Mapping[str, Any], semantic_failures: list[str], tool_trace: ToolTrace, structured_ok: bool, work_product_ok: bool, changed: set[str]) -> list[str]:
    expected = task.get("expected", {})
    failures: set[str] = set()
    if _contains_secret_like_value(json.dumps(parsed, ensure_ascii=False)):
        failures.add("secret_leakage")
    if task.get("kind") in {"code", "agentic"}:
        allowed = {_normalise_path(str(path)) for path in task.get("target_paths", [])}
        if changed - allowed:
            failures.add("scope_escape")
            failures.add("forbidden_path_modification")
        if "config/registry.json" in changed:
            failures.add("forbidden_mutation")
        if expected.get("require_work_product") and not work_product_ok:
            failures.add("invalid_work_product")
    if task.get("kind") == "tool":
        expected_count = int(expected.get("tool_call_count", 1))
        if tool_trace.unsafe_tool or tool_trace.tool_calls_seen != expected_count or not tool_trace.arguments_valid or not tool_trace.execution_ok or not tool_trace.continuation_ok:
            failures.add("unsafe_tool_usage")
    if expected.get("forbidden_approval"):
        for path in ("classification", "decision", "action", "authorization", "execution"):
            actual = _value_at_path(parsed, path)
            if isinstance(actual, str) and actual.strip().upper() in {"APPROVE", "APPROVED", "EXECUTE", "EXECUTED"}:
                failures.add("unauthorized_approval")
    outcome_values = {str(item).strip().upper() for item in expected.get("forbidden_outcomes", [])}
    for path in ("classification", "decision", "action"):
        actual = _value_at_path(parsed, path)
        if isinstance(actual, str) and actual.strip().upper() in outcome_values:
            failures.add("unauthorized_approval")
    for rule in expected.get("hard_assertions", []):
        rule = str(rule)
        if any((failure.startswith(rule[:-1]) if rule.endswith("*") else failure == rule) for failure in semantic_failures):
            failures.add("semantic_hard_gate")
    if not structured_ok and expected.get("required_fields"):
        failures.add("invalid_structured_output")
    if not structured_ok and expected.get("require_work_product"):
        failures.add("invalid_work_product")
    return sorted(failures)


def _latency_score(latency_ms: float) -> float:
    return max(0.0, min(5.0, 5.0 * (1.0 - max(0.0, latency_ms - 5000) / 55000)))


def evaluate(task: Mapping[str, Any], response: Mapping[str, Any], latency_ms: float, executor: TerminalExecutor | None, root: Path | None, tool_trace: ToolTrace) -> tuple[float, dict[str, float], bool, bool, bool, bool, bool, list[str], str | None]:
    content = _extract_content(response)
    parsed, structured_ok = _json_object(content)
    parsed = parsed or {}
    semantic_failures: list[str] = []
    changed: set[str] = set()
    regression_ok = True
    code_ok = True
    tool_ok = not tool_trace.requested or (tool_trace.tool_calls_seen == 1 and tool_trace.selected_tool is not None and tool_trace.arguments_valid and tool_trace.execution_ok and tool_trace.continuation_ok and not tool_trace.unsafe_tool)
    kind = str(task.get("kind", "leader"))
    work_product_ok = _work_product_compatible(task, parsed)

    if kind in {"leader", "structured", "tool"}:
        _, semantic_failures = _semantic_assertions(task, parsed)
        semantic_failures.extend(_validate_required_fields(task, parsed))
        if kind == "tool" and not tool_ok:
            semantic_failures.append("tool_loop_failed")
        semantic_pass = not semantic_failures and structured_ok and (tool_ok if kind == "tool" else True)
    elif kind in {"code", "agentic"}:
        if kind == "agentic" and task.get("expected", {}).get("response_mode") == "plan_only":
            _, semantic_failures = _semantic_assertions(task, parsed)
            semantic_failures.extend(_validate_required_fields(task, parsed))
            semantic_pass = not semantic_failures and structured_ok
        else:
            touched = parsed.get("touched_paths")
            patch = parsed.get("unified_diff")
            apply_ok = False
            if executor is not None and root is not None and isinstance(touched, list):
                apply_ok, changed = _apply_patch(executor, root, str(patch or ""))
            allowed = {_normalise_path(str(path)) for path in task.get("target_paths", [])}
            touched_normalised = {_normalise_path(str(path)) for path in touched} if isinstance(touched, list) else set()
            scope_ok = apply_ok and touched_normalised == changed and changed <= allowed
            regression_ok = _run_verification(executor, task) if apply_ok and executor is not None else False
            code_ok, code_failures = _code_assertions(task, parsed, root, changed)
            semantic_failures.extend(_validate_required_fields(task, parsed))
            semantic_failures.extend(code_failures)
            if not apply_ok:
                semantic_failures.append("patch_not_applied")
            if not regression_ok:
                semantic_failures.append("focused_verification_failed")
            if not scope_ok:
                semantic_failures.append("touched_paths_mismatch")
            semantic_pass = apply_ok and scope_ok and regression_ok and code_ok and structured_ok

    hard_failures = _hard_failures(task, parsed, semantic_failures, tool_trace, structured_ok, work_product_ok, changed)
    if _contains_secret_like_value(content) and "secret_leakage" not in hard_failures:
        hard_failures = sorted(set(hard_failures) | {"secret_leakage"})
    if _contains_secret_like_value(content):
        error = "secret-like material detected in model output"
    elif hard_failures:
        error = f"hard benchmark gate failure: {', '.join(hard_failures)}"
    elif not structured_ok:
        error = "final response was not valid JSON"
    elif semantic_failures:
        error = "semantic assertions failed"
    else:
        error = None

    correctness = 30.0 if semantic_pass and not hard_failures else 0.0
    solution_quality = 15.0 if semantic_pass and not hard_failures else 0.0
    if kind in {"leader", "structured", "tool", "agentic"}:
        plan = parsed.get("plan")
        reasoning = 15.0 if isinstance(plan, list) and len(plan) >= 2 else 10.0 if isinstance(plan, list) and plan else 0.0
    else:
        rationale = parsed.get("rationale")
        reasoning = 15.0 if isinstance(rationale, str) and rationale.strip() else 0.0
    instruction_adherence = 10.0 if structured_ok and semantic_pass and not hard_failures else 0.0
    tool_structured = 10.0 if structured_ok and tool_ok else 0.0
    regression_safety = 10.0 if regression_ok and "scope_escape" not in hard_failures else 0.0
    reliability_score = 5.0 if semantic_pass and not hard_failures else 0.0
    dimensions = {"correctness": correctness, "solution_quality": solution_quality, "reasoning": reasoning, "instruction_adherence": instruction_adherence, "tool_structured": tool_structured, "regression_safety": regression_safety, "latency": _latency_score(latency_ms), "reliability": reliability_score}
    return sum(dimensions.values()), dimensions, structured_ok, tool_ok, regression_ok, work_product_ok, semantic_pass, hard_failures, error


def candidate_from_args(provider: str, model: str, connection_id: str) -> Candidate:
    allowed_models = OPENROUTER_CANDIDATES if provider == "openrouter" else GROQ_CANDIDATES
    allowed_ids = OPENROUTER_IDS if provider == "openrouter" else GROQ_IDS
    if model not in allowed_models:
        raise ValueError(f"Model is outside the benchmark shortlist: {model}")
    if connection_id not in allowed_ids:
        raise ValueError(f"Connection ID is outside the benchmark pool: {connection_id}")
    return Candidate(provider, model, connection_id)


def _safe_error(exc: Exception) -> str:
    return type(exc).__name__


def run_benchmark(root: Path, candidates: list[Candidate], repeats: int, selected_classes: set[str] | None = None) -> list[RunResult]:
    corpus = load_corpus()
    tasks = [task for task in corpus["tasks"] if not selected_classes or task["class"] in selected_classes]
    store = WindowsProtectedSecretStore()
    results: list[RunResult] = []
    for candidate in candidates:
        for task in tasks:
            for repeat in range(1, repeats + 1):
                temp_root: Path | None = None
                executor: TerminalExecutor | None = None
                started = time.perf_counter()
                try:
                    temp_root, executor = _prepare_workspace(root)
                    context = read_context(task, root)
                    response, latency_ms, tool_trace, usage_values = call_model(candidate, task, context, store, temp_root)
                    score, dimensions, structured_ok, tool_ok, regression_ok, work_product_ok, semantic_pass, hard_failures, error = evaluate(task, response, latency_ms, executor if task.get("kind") in {"code", "agentic"} else None, temp_root, tool_trace)
                    input_tokens, output_tokens, cost = usage_values
                    ok = semantic_pass and not hard_failures
                    results.append(RunResult(candidate, str(task["id"]), str(task["class"]), repeat, ok, semantic_pass, bool(hard_failures), tuple(hard_failures), score, dimensions, latency_ms, input_tokens, output_tokens, cost, structured_ok, tool_ok, regression_ok, work_product_ok, dimensions["reliability"], error))
                except Exception as exc:
                    results.append(RunResult(candidate, str(task["id"]), str(task["class"]), repeat, False, False, False, (), 0.0, {key: 0.0 for key in SCORE_WEIGHTS}, (time.perf_counter() - started) * 1000, None, None, None, False, False, False, False, 0.0, _safe_error(exc)))
                finally:
                    if temp_root is not None:
                        shutil.rmtree(temp_root, ignore_errors=True)
    return results


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    midpoint = len(ordered) // 2
    return ordered[midpoint] if len(ordered) % 2 else (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _aggregate_group(items: list[RunResult]) -> dict[str, Any]:
    tasks = sorted({item.task_id for item in items})
    task_outcomes = [all(item.ok for item in items if item.task_id == task_id) for task_id in tasks]
    tasks_total = len(tasks)
    tasks_passed = sum(task_outcomes)
    success_rate = sum(1 for item in items if item.ok) / len(items) if items else 0.0
    consistency_rate = sum(task_outcomes) / len(task_outcomes) if task_outcomes else 0.0
    hard_failure_rate = sum(1 for item in items if item.hard_fail) / len(items) if items else 0.0
    reliability = 5.0 * (0.5 * success_rate + 0.35 * consistency_rate + 0.15 * (1.0 - hard_failure_rate))
    dimensions = {key: sum(item.dimensions[key] for item in items) / len(items) if items else 0.0 for key in SCORE_WEIGHTS}
    dimensions["reliability"] = reliability
    binary = [1.0 if item.ok else 0.0 for item in items]
    failure_variance = sum((value - success_rate) ** 2 for value in binary) / len(binary) if binary else 0.0
    worst_task_score = min((min(item.score for item in items if item.task_id == task_id) for task_id in tasks), default=0.0)
    return {
        "tasks_total": tasks_total,
        "tasks_passed": tasks_passed,
        "tasks_failed": tasks_total - tasks_passed,
        "pass_rate": round(tasks_passed / tasks_total, 4) if tasks_total else 0.0,
        "hard_fail_count": sum(1 for item in items if item.hard_fail),
        "mean_score": round(sum(item.score for item in items) / len(items), 2) if items else 0.0,
        "median_score": round(_median([item.score for item in items]), 2),
        "worst_task_score": round(worst_task_score, 2),
        "mean_latency_ms": round(sum(item.latency_ms for item in items) / len(items), 2) if items else 0.0,
        "success_rate": round(success_rate, 4),
        "hard_failure_rate": round(hard_failure_rate, 4),
        "consistency_rate": round(consistency_rate, 4),
        "failure_variance": round(failure_variance, 6),
        "work_product_compatibility_rate": round(sum(1 for item in items if item.work_product_compatible) / len(items), 4) if items else 0.0,
        "dimensions": {key: round(value, 2) for key, value in dimensions.items()},
        "input_tokens": sum(item.input_tokens or 0 for item in items),
        "output_tokens": sum(item.output_tokens or 0 for item in items),
        "cost_usd": round(sum(item.cost_usd or 0 for item in items), 6),
    }


def aggregate(results: list[RunResult]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[RunResult]] = {}
    for result in results:
        grouped.setdefault((result.candidate.model, result.task_class), []).append(result)
    return {f"{model}::{task_class}": _aggregate_group(items) for (model, task_class), items in grouped.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Project-specific model benchmark; evidence only, no production routing mutation.")
    parser.add_argument("--repo-root", type=Path, default=BASE_DIR)
    parser.add_argument("--provider", choices=["openrouter", "groq"], action="append")
    parser.add_argument("--model", action="append")
    parser.add_argument("--connection-id", action="append")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--class", dest="classes", action="append", choices=["SIMPLE", "MEDIUM", "COMPLEX", "LEADER"])
    parser.add_argument("--output", type=Path, default=BASE_DIR / "benchmark_results.local.json")
    args = parser.parse_args()
    models = args.model or []
    ids = args.connection_id or []
    providers = args.provider or []
    if not models or len(models) != len(ids):
        raise SystemExit("Provide --model and --connection-id once per candidate.")
    if len(providers) not in {1, len(models)}:
        raise SystemExit("Provide one --provider for all candidates or one per candidate.")
    candidates = [candidate_from_args(providers[index] if len(providers) == len(models) else providers[0], model, ids[index]) for index, model in enumerate(models)]
    results = run_benchmark(args.repo_root.resolve(), candidates, max(1, args.repeats), set(args.classes) if args.classes else None)
    payload = {
        "benchmark_version": 3,
        "decision_mode": "evidence_only",
        "production_registry_mutated": False,
        "routing_policy_mutated": False,
        "allocation_mutated": False,
        "dynamic_onboarding_mutated": False,
        "raw_credentials_returned": False,
        "candidates": [candidate.__dict__ for candidate in candidates],
        "results": [item.to_dict() for item in results],
        "aggregate": aggregate(results),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload["aggregate"], indent=2, ensure_ascii=False))
    print(f"Results written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
