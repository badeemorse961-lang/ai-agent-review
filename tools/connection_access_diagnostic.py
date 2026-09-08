from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import requests

from protected_secret_store import SecretStoreError, WindowsProtectedSecretStore

CONNECTIONS_FILE = BASE / "connections.json"

TARGETS = {
    "GROQ-01": {"provider": "groq", "model": "openai/gpt-oss-120b", "endpoint": "https://api.groq.com/openai/v1/models"},
    "GROQ-02": {"provider": "groq", "model": "openai/gpt-oss-20b", "endpoint": "https://api.groq.com/openai/v1/models"},
    "OR-03": {"provider": "openrouter", "model": "z-ai/glm-5.3-flash:free", "endpoint": "https://openrouter.ai/api/v1/models"},
    "OR-05": {"provider": "openrouter", "model": "minimax/minimax-m3:free", "endpoint": "https://openrouter.ai/api/v1/models"},
}

SECRET_PATTERNS = [
    re.compile(r"sk-or-v1-[A-Za-z0-9_-]+", re.I),
    re.compile(r"gsk_[A-Za-z0-9_-]+", re.I),
    re.compile(r"authorization\s*:\s*bearer\s+\S+", re.I),
    re.compile(r"\bbearer\s+[A-Za-z0-9._-]{20,}", re.I),
]

SENSITIVE_KEYS = re.compile(r"(api[_-]?key|authorization|credential|password|secret|token)", re.I)
SAFE_DIAGNOSTIC_KEYS = {
    "secret_store",
    "credential_retrievable",
    "credential_validated",
    "raw_credentials_returned",
    "key_fingerprint_present",
    "classification",
    "model_present_in_listing",
}


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): (
                sanitize(v)
                if str(k) in SAFE_DIAGNOSTIC_KEYS
                else ("[REDACTED]" if SENSITIVE_KEYS.search(str(k)) else sanitize(v))
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        text = value
        for pattern in SECRET_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text[:2000] + ("...[TRUNCATED]" if len(text) > 2000 else "")
    return value


def load_metadata() -> dict[str, Any]:
    data = json.loads(CONNECTIONS_FILE.read_text(encoding="utf-8"))
    connections = data.get("connections")
    if not isinstance(connections, dict):
        raise RuntimeError("connections.json has no valid connections object")
    return connections


def classify_http(status: int | None, body: Any, model: str) -> tuple[str, str]:
    if status is None:
        return "PROVIDER_FAILURE", "No provider response was received."
    if 200 <= status < 300:
        if isinstance(body, dict):
            rows = body.get("data")
            if isinstance(rows, list):
                ids = {
                    item.get("id")
                    for item in rows
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
                if model in ids:
                    return "READY", "Credential accepted and candidate model is present in provider model listing."
                return "MODEL_ID_NOT_AVAILABLE", "Credential request succeeded, but candidate model was not present in the provider model listing."
        return "READY", "Provider authentication request succeeded."
    if status in (401, 403):
        return "PROVIDER_FAILURE", "Provider rejected authentication/authorization."
    if status == 404:
        return "PROVIDER_FAILURE", "Provider endpoint or resource was not found."
    if status in (408, 409, 425, 429):
        return "PROVIDER_FAILURE", "Provider request was rejected or unavailable due to rate/quota/conflict/timeout."
    if 400 <= status < 500:
        return "PROVIDER_FAILURE", "Provider rejected the request."
    if 500 <= status < 600:
        return "PROVIDER_FAILURE", "Provider returned a server-side error."
    return "UNRESOLVED", "Unexpected provider HTTP status."


def _safe_secret_store_stage(connection_id: str, expected_provider: str) -> tuple[str, bool, str | None]:
    """Return (stage, credential_retrievable, secret). The secret is never persisted or returned by the caller."""
    store = WindowsProtectedSecretStore()

    try:
        store_path = Path(store.path)
        encrypted = store_path.read_bytes()
    except OSError:
        return "STORE_ACCESS_FAILURE", False, None

    try:
        plaintext = store._backend.unprotect(encrypted)  # diagnostic-only, read-only inspection
    except SecretStoreError as exc:
        if "CryptUnprotectData failed" in str(exc):
            return "DPAPI_READ_FAILURE", False, None
        return "STORE_ACCESS_FAILURE", False, None
    except OSError:
        return "STORE_ACCESS_FAILURE", False, None

    try:
        data = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return "STORE_ACCESS_FAILURE", False, None

    connections = data.get("connections") if isinstance(data, dict) else None
    if not isinstance(connections, dict):
        return "STORE_ACCESS_FAILURE", False, None

    item = connections.get(connection_id)
    if not isinstance(item, dict):
        return "SECRET_RECORD_MISSING", False, None

    if item.get("provider") != expected_provider:
        return "CONNECTION_ID_MISMATCH", False, None

    secret = item.get("secret")
    if not isinstance(secret, str) or not secret:
        return "SECRET_RECORD_MISSING", False, None

    return "READY", True, secret


def diagnostic(connection_id: str) -> dict[str, Any]:
    meta = load_metadata()
    raw = meta.get(connection_id)
    result: dict[str, Any] = {
        "connection_id": connection_id,
        "metadata": None,
        "secret_store": None,
        "credential_retrievable": False,
        "provider": None,
        "model": TARGETS[connection_id]["model"],
        "endpoint": TARGETS[connection_id]["endpoint"],
        "provider_http": None,
        "classification": "UNRESOLVED",
    }

    if not isinstance(raw, dict):
        result["classification"] = "LOCAL_ENVIRONMENT_FAILURE"
        result["secret_store"] = "CONNECTION_ID_MISMATCH"
        result["error"] = "Connection metadata record not found."
        return result

    result["metadata"] = {
        "provider": raw.get("provider"),
        "status": raw.get("status"),
        "active": raw.get("active"),
        "role": raw.get("role"),
        "credential_validated": raw.get("credential_validated"),
        "validation_required": raw.get("validation_required"),
        "key_fingerprint_present": bool(raw.get("key_fingerprint")),
    }
    result["provider"] = raw.get("provider")

    expected_provider = TARGETS[connection_id]["provider"]
    if raw.get("provider") != expected_provider:
        result["classification"] = "LOCAL_ENVIRONMENT_FAILURE"
        result["secret_store"] = "CONNECTION_ID_MISMATCH"
        result["error"] = "Connection provider metadata does not match diagnostic target."
        return result

    try:
        stage, retrievable, secret = _safe_secret_store_stage(connection_id, expected_provider)
        result["secret_store"] = stage
        result["credential_retrievable"] = retrievable
    except SecretStoreError as exc:
        result["secret_store"] = "STORE_ACCESS_FAILURE"
        result["error"] = type(exc).__name__
        result["classification"] = "LOCAL_ENVIRONMENT_FAILURE"
        return result
    except Exception as exc:
        result["secret_store"] = "STORE_ACCESS_FAILURE"
        result["error"] = type(exc).__name__
        result["classification"] = "LOCAL_ENVIRONMENT_FAILURE"
        return result

    if not retrievable or not isinstance(secret, str) or not secret:
        result["classification"] = "LOCAL_ENVIRONMENT_FAILURE"
        return result

    headers = {
        "Authorization": f"Bearer {secret}",
        "Accept": "application/json",
        "User-Agent": "AI-Agent-Access-Readiness-Diagnostic",
    }
    try:
        response = requests.get(
            TARGETS[connection_id]["endpoint"],
            headers=headers,
            timeout=(10, 30),
        )
        try:
            body = response.json()
        except ValueError:
            body = response.text
        safe_body = sanitize(body)
        category, message = classify_http(response.status_code, body, TARGETS[connection_id]["model"])
        result["provider_http"] = {
            "status_code": response.status_code,
            "category": category,
            "sanitized_body": safe_body,
            "sanitized_message": message,
            "model_present_in_listing": (
                bool(isinstance(body, dict))
                and isinstance(body.get("data"), list)
                and TARGETS[connection_id]["model"] in {
                    item.get("id")
                    for item in body["data"]
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                }
            ),
        }
        if category == "READY":
            result["classification"] = "READY"
        elif category == "MODEL_ID_NOT_AVAILABLE":
            result["classification"] = "MODEL_ID_NOT_AVAILABLE"
        else:
            result["classification"] = "PROVIDER_FAILURE"
    except requests.RequestException as exc:
        result["provider_http"] = {
            "status_code": None,
            "category": "PROVIDER_FAILURE",
            "sanitized_body": None,
            "sanitized_message": type(exc).__name__,
        }
        result["classification"] = "PROVIDER_FAILURE"

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only provider access readiness diagnostic.")
    parser.add_argument("--output", type=Path, default=Path("connection_access_diagnostic.json"))
    args = parser.parse_args()

    payload = {
        "diagnostic_version": 2,
        "targets": list(TARGETS),
        "production_registry_mutated": False,
        "routing_policy_mutated": False,
        "allocation_mutated": False,
        "dynamic_onboarding_mutated": False,
        "raw_credentials_returned": False,
        "results": [diagnostic(connection_id) for connection_id in TARGETS],
    }
    safe_payload = sanitize(payload)
    args.output.write_text(
        json.dumps(safe_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(safe_payload, indent=2, ensure_ascii=False))
    print(f"DIAGNOSTIC_WRITTEN={args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
