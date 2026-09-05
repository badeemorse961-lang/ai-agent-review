from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parent

GROQ_FILE = BASE_DIR / "groq_keys.txt"
OPENROUTER_FILE = BASE_DIR / "openrouter_keys.txt"

GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

TIMEOUT = 20


def load_keys(path: Path) -> list[str]:
    """Read non-empty lines and ignore surrounding whitespace."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    keys: list[str] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.strip()
        if key:
            keys.append(key)

    return keys


def validate_groq(key: str) -> tuple[bool, str, list[str]]:
    """Validate Groq key by reading the model catalog."""
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    try:
        response = requests.get(
            GROQ_MODELS_URL,
            headers=headers,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, f"NETWORK_ERROR: {type(exc).__name__}", []

    if response.status_code != 200:
        return False, f"HTTP_{response.status_code}", []

    try:
        data: dict[str, Any] = response.json()
    except ValueError:
        return False, "INVALID_JSON_RESPONSE", []

    models = data.get("data", [])
    model_ids: list[str] = []

    if isinstance(models, list):
        for model in models:
            if isinstance(model, dict):
                model_id = model.get("id")
                if isinstance(model_id, str):
                    model_ids.append(model_id)

    return True, "VALID", sorted(model_ids)


def validate_openrouter(key: str) -> tuple[bool, str, list[str]]:
    """Validate OpenRouter key by reading the model catalog."""
    headers = {
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }

    try:
        response = requests.get(
            OPENROUTER_MODELS_URL,
            headers=headers,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, f"NETWORK_ERROR: {type(exc).__name__}", []

    if response.status_code != 200:
        return False, f"HTTP_{response.status_code}", []

    try:
        data: dict[str, Any] = response.json()
    except ValueError:
        return False, "INVALID_JSON_RESPONSE", []

    models = data.get("data", [])
    model_ids: list[str] = []

    if isinstance(models, list):
        for model in models:
            if isinstance(model, dict):
                model_id = model.get("id")
                if isinstance(model_id, str):
                    model_ids.append(model_id)

    return True, "VALID", sorted(model_ids)


def find_relevant_models(model_ids: list[str]) -> list[str]:
    """Show only models relevant to our current project."""
    keywords = (
        "gpt-oss",
        "nemotron",
        "qwen",
        "llama",
        "deepseek",
    )

    matches = [
        model_id
        for model_id in model_ids
        if any(keyword in model_id.lower() for keyword in keywords)
    ]

    return matches[:30]


def main() -> int:
    try:
        groq_keys = load_keys(GROQ_FILE)
        openrouter_keys = load_keys(OPENROUTER_FILE)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print("=" * 70)
    print("AI-Agent API CONNECTION CHECK")
    print("=" * 70)
    print()

    print(f"Groq keys found       : {len(groq_keys)}")
    print(f"OpenRouter keys found : {len(openrouter_keys)}")
    print()

    # Duplicate detection without printing any secret.
    groq_duplicates = len(groq_keys) - len(set(groq_keys))
    openrouter_duplicates = len(openrouter_keys) - len(set(openrouter_keys))

    print(f"Groq duplicate entries       : {groq_duplicates}")
    print(f"OpenRouter duplicate entries : {openrouter_duplicates}")
    print()

    valid_groq = 0
    valid_openrouter = 0

    print("-" * 70)
    print("GROQ")
    print("-" * 70)

    for index, key in enumerate(groq_keys, start=1):
        connection_id = f"GROQ-{index:02d}"

        ok, status, models = validate_groq(key)

        if ok:
            valid_groq += 1

        print(f"{connection_id:<12} {status}")

        if ok:
            relevant = find_relevant_models(models)

            if relevant:
                print("  Relevant models:")
                for model_id in relevant:
                    print(f"    - {model_id}")
            else:
                print(f"  Models visible: {len(models)}")

    print()

    print("-" * 70)
    print("OPENROUTER")
    print("-" * 70)

    for index, key in enumerate(openrouter_keys, start=1):
        connection_id = f"OR-{index:02d}"

        ok, status, models = validate_openrouter(key)

        if ok:
            valid_openrouter += 1

        print(f"{connection_id:<12} {status}")

        if ok:
            relevant = find_relevant_models(models)

            if relevant:
                print("  Relevant models:")
                for model_id in relevant:
                    print(f"    - {model_id}")
            else:
                print(f"  Models visible: {len(models)}")

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Groq       : {valid_groq}/{len(groq_keys)} valid")
    print(f"OpenRouter : {valid_openrouter}/{len(openrouter_keys)} valid")
    print()
    print("No roles assigned. No inference requests were sent.")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())