from __future__ import annotations

import json
import time
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent

GROQ_KEYS = BASE_DIR / "groq_keys.txt"
OR_KEYS = BASE_DIR / "openrouter_keys.txt"

GROQ_CHAT = "https://api.groq.com/openai/v1/chat/completions"
OR_CHAT = "https://openrouter.ai/api/v1/chat/completions"
OR_MODELS = "https://openrouter.ai/api/v1/models"

TIMEOUT = 90

NEMOTRON_FREE_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


LEADER_TASK = """
You are evaluating whether you should act as the CENTRAL LEADER
of an autonomous software engineering agent.

You are NOT being asked to write code.

Analyze this project situation:

Project:
A Python e-commerce service.

Files:
- cart.py: cart calculations
- pricing.py: discount and pricing rules
- orders.py: order creation
- app.py: application entry point
- tests/: automated tests
- README.md: requirements

Known situation:
1. A discount requirement says:
   "Orders with total >= 100 receive the bulk discount."
2. The implementation currently appears to use:
   if total > 100:
       apply_discount()
3. Some tests are failing.
4. One developer suggests modifying app.py.
5. Another suggests rewriting pricing.py completely.
6. The available evidence has not yet proved that app.py is defective.
7. A reviewer must independently validate the final change.

As CENTRAL LEADER, produce a structured management decision.

Your response MUST contain exactly these sections:

1. PROJECT_UNDERSTANDING
2. ROOT_PROBLEM
3. PLAN
4. TASK_DECOMPOSITION
5. EXPERT_ASSIGNMENTS
6. EXECUTION_ORDER
7. RISKS
8. TEST_AND_VERIFICATION_PLAN
9. FAILURE_HANDLING
10. STOP_CONDITIONS
11. FILES_TO_MODIFY
12. FILES_NOT_TO_MODIFY
13. FINAL_LEADER_DECISION

Important:
- Do not invent requirements.
- Do not assume app.py is broken without evidence.
- Do not rewrite files unnecessarily.
- Prefer the smallest safe change.
- Explain when an expert should be consulted.
- Explain what happens if tests fail.
- Explain when execution must stop.
- The goal is safe autonomous engineering management, not code generation.
"""


def read_keys(path: Path) -> list[str]:
    """Read non-empty key lines without ever printing their values."""
    if not path.exists():
        raise FileNotFoundError(f"Missing key file: {path}")

    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def save_result(provider: str, model: str, text: str) -> Path:
    """Save a successful benchmark result locally."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    path = BASE_DIR / f"leader_result_{provider}_{timestamp}.json"

    result = {
        "provider": provider,
        "model": model,
        "benchmark": "leader_management",
        "result": text,
    }

    path.write_text(
        json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return path


def save_diagnostic(provider: str, data: object) -> Path:
    """
    Save a diagnostic response locally.

    This contains API response information only.
    No API key is written here.
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    path = BASE_DIR / f"leader_diagnostic_{provider}_{timestamp}.json"

    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return path


def extract_content(data: dict) -> str:
    """
    Extract model text from common OpenRouter/OpenAI-compatible
    response formats.
    """

    # Standard OpenAI-compatible format.
    choices = data.get("choices")

    if isinstance(choices, list) and choices:
        first_choice = choices[0]

        if isinstance(first_choice, dict):
            message = first_choice.get("message")

            if isinstance(message, dict):
                content = message.get("content")

                if isinstance(content, str):
                    return content

            text = first_choice.get("text")

            if isinstance(text, str):
                return text

    # Some provider responses may expose an output field.
    output = data.get("output")

    if isinstance(output, str):
        return output

    # Some responses expose content directly.
    content = data.get("content")

    if isinstance(content, str):
        return content

    raise RuntimeError(
        "Model response did not contain recognizable text content."
    )


def groq_request(key: str) -> str:
    """Send one leadership benchmark request to Groq."""
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are being evaluated as a software engineering leader."
                ),
            },
            {
                "role": "user",
                "content": LEADER_TASK,
            },
        ],
        "temperature": 0,
    }

    response = requests.post(
        GROQ_CHAT,
        headers=headers,
        json=payload,
        timeout=TIMEOUT,
    )

    print(f"   HTTP status: {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            "Groq returned a non-JSON response."
        )

    if response.status_code != 200:
        diagnostic = {
            "status_code": response.status_code,
            "response_keys": list(data.keys())
            if isinstance(data, dict)
            else type(data).__name__,
            "error": data.get("error")
            if isinstance(data, dict)
            else None,
        }

        diagnostic_file = save_diagnostic(
            "groq",
            diagnostic,
        )

        print(
            f"   Diagnostic saved: {diagnostic_file.name}"
        )

        response.raise_for_status()

    if not isinstance(data, dict):
        raise RuntimeError(
            "Groq returned an unexpected JSON structure."
        )

    return extract_content(data)


def get_openrouter_nemotron(key: str) -> str | None:
    """
    Check the OpenRouter catalog for the exact FREE Nemotron model.
    No inference request is made here.
    """
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    response = requests.get(
        OR_MODELS,
        headers=headers,
        timeout=TIMEOUT,
    )

    print(f"   Model catalog HTTP status: {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            "OpenRouter model catalog returned non-JSON data."
        )

    if response.status_code != 200:
        diagnostic = {
            "status_code": response.status_code,
            "response_keys": list(data.keys())
            if isinstance(data, dict)
            else type(data).__name__,
            "error": data.get("error")
            if isinstance(data, dict)
            else None,
        }

        diagnostic_file = save_diagnostic(
            "openrouter_catalog",
            diagnostic,
        )

        print(
            f"   Diagnostic saved: {diagnostic_file.name}"
        )

        response.raise_for_status()

    if not isinstance(data, dict):
        raise RuntimeError(
            "OpenRouter model catalog returned an unexpected structure."
        )

    models = data.get("data", [])

    if not isinstance(models, list):
        raise RuntimeError(
            "OpenRouter model catalog has unexpected 'data' structure."
        )

    for model in models:
        if not isinstance(model, dict):
            continue

        model_id = model.get("id")

        if model_id == NEMOTRON_FREE_MODEL:
            return NEMOTRON_FREE_MODEL

    return None


def openrouter_request(key: str, model: str) -> str:
    """Send one leadership benchmark request to OpenRouter."""
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "AI-Agent Leader Benchmark",
    }

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are being evaluated as a software engineering leader."
                ),
            },
            {
                "role": "user",
                "content": LEADER_TASK,
            },
        ],
        "temperature": 0,
    }

    response = requests.post(
        OR_CHAT,
        headers=headers,
        json=payload,
        timeout=TIMEOUT,
    )

    print(f"   HTTP status: {response.status_code}")

    try:
        data = response.json()
    except ValueError:
        diagnostic_file = save_diagnostic(
            "openrouter_response",
            {
                "status_code": response.status_code,
                "response_prefix": response.text[:500],
            },
        )

        print(
            f"   Diagnostic saved: {diagnostic_file.name}"
        )

        raise RuntimeError(
            "OpenRouter returned a non-JSON response."
        )

    if response.status_code != 200:
        diagnostic = {
            "status_code": response.status_code,
            "response_keys": list(data.keys())
            if isinstance(data, dict)
            else type(data).__name__,
            "error": data.get("error")
            if isinstance(data, dict)
            else None,
        }

        diagnostic_file = save_diagnostic(
            "openrouter_response",
            diagnostic,
        )

        print(
            f"   Diagnostic saved: {diagnostic_file.name}"
        )

        response.raise_for_status()

    if not isinstance(data, dict):
        diagnostic_file = save_diagnostic(
            "openrouter_response",
            {
                "status_code": response.status_code,
                "response_type": type(data).__name__,
            },
        )

        print(
            f"   Diagnostic saved: {diagnostic_file.name}"
        )

        raise RuntimeError(
            "OpenRouter returned an unexpected JSON structure."
        )

    try:
        return extract_content(data)

    except RuntimeError as exc:
        diagnostic = {
            "status_code": response.status_code,
            "top_level_keys": list(data.keys()),
            "usage": data.get("usage"),
            "model": data.get("model"),
            "id": data.get("id"),
            "error": data.get("error"),
        }

        diagnostic_file = save_diagnostic(
            "openrouter_response",
            diagnostic,
        )

        print(
            f"   Diagnostic saved: {diagnostic_file.name}"
        )

        raise RuntimeError(
            f"{exc}"
        ) from exc


def main() -> int:
    try:
        groq_keys = read_keys(GROQ_KEYS)
        or_keys = read_keys(OR_KEYS)

    except Exception as exc:
        print(
            f"ERROR READING KEY FILES: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1

    if not groq_keys:
        print("ERROR: No Groq keys found.")
        return 1

    if not or_keys:
        print("ERROR: No OpenRouter keys found.")
        return 1

    print("=" * 70)
    print("CENTRAL LEADER BENCHMARK")
    print("=" * 70)

    # Exactly one connection per candidate.
    groq_key = groq_keys[0]
    or_key = or_keys[0]

    # ---------------------------------------------------------------
    # GPT-OSS 120B / GROQ
    # ---------------------------------------------------------------

    print()
    print("1) GPT-OSS 120B / Groq")
    print("   Sending one leadership benchmark request...")

    groq_success = False

    try:
        groq_result = groq_request(groq_key)

        groq_file = save_result(
            "groq",
            "openai/gpt-oss-120b",
            groq_result,
        )

        groq_success = True

        print("   SUCCESS")
        print(f"   Saved: {groq_file.name}")

    except requests.HTTPError as exc:
        status = (
            exc.response.status_code
            if exc.response is not None
            else "UNKNOWN"
        )

        print(
            f"   FAILED: HTTP {status}"
        )

    except Exception as exc:
        print(
            f"   FAILED: "
            f"{type(exc).__name__}: {exc}"
        )

    # ---------------------------------------------------------------
    # NEMOTRON 3 ULTRA FREE / OPENROUTER
    # ---------------------------------------------------------------

    print()
    print("2) Nemotron 3 Ultra / OpenRouter")
    print("   Checking exact FREE model availability first...")

    nemotron_model: str | None = None
    openrouter_success = False

    try:
        nemotron_model = get_openrouter_nemotron(or_key)

        if not nemotron_model:
            print(
                "   NOT AVAILABLE:"
                f" {NEMOTRON_FREE_MODEL}"
            )

        else:
            print(
                f"   Found: {nemotron_model}"
            )

            print(
                "   Sending one leadership benchmark request..."
            )

            or_result = openrouter_request(
                or_key,
                nemotron_model,
            )

            or_file = save_result(
                "openrouter",
                nemotron_model,
                or_result,
            )

            openrouter_success = True

            print("   SUCCESS")
            print(f"   Saved: {or_file.name}")

    except requests.HTTPError as exc:
        status = (
            exc.response.status_code
            if exc.response is not None
            else "UNKNOWN"
        )

        print(
            f"   FAILED: HTTP {status}"
        )

    except Exception as exc:
        print(
            f"   FAILED: "
            f"{type(exc).__name__}: {exc}"
        )

    # ---------------------------------------------------------------
    # SUMMARY
    # ---------------------------------------------------------------

    print()
    print("=" * 70)
    print("BENCHMARK COMPLETE")
    print("=" * 70)

    print(
        "GPT-OSS benchmark : "
        f"{'SUCCESS' if groq_success else 'FAILED'}"
    )

    if nemotron_model:
        print(
            "Nemotron benchmark : "
            f"{'SUCCESS' if openrouter_success else 'FAILED'}"
        )
    else:
        print(
            "Nemotron benchmark : NOT AVAILABLE"
        )

    print()
    print(
        "Only one request per candidate was attempted."
    )
    print(
        "No role assignment was changed."
    )
    print(
        "No project files were modified."
    )

    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())