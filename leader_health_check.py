from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from config_registry import validate_registry


BASE_DIR = Path(__file__).resolve().parent
KEY_FILE = BASE_DIR / "openrouter_keys.txt"
OUTPUT_FILE = BASE_DIR / "leader_health.json"
CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 20
TEST_MESSAGE = "Health check only. Reply with exactly: OK"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_keys(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing key file: {path.name}")
    keys = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not keys:
        raise RuntimeError("No OpenRouter keys were found.")
    return keys


def create_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=0)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def classify_http_status(status_code: int) -> str:
    if status_code == 200:
        return "OK"
    if status_code == 401:
        return "AUTHENTICATION_FAILED"
    if status_code == 402:
        return "PAYMENT_OR_MODEL_ACCESS_REQUIRED"
    if status_code == 403:
        return "FORBIDDEN"
    if status_code == 408:
        return "REQUEST_TIMEOUT"
    if status_code == 429:
        return "RATE_LIMITED"
    if 500 <= status_code <= 599:
        return "PROVIDER_OR_SERVER_ERROR"
    if 400 <= status_code <= 499:
        return "CLIENT_ERROR"
    if 200 <= status_code <= 299:
        return "OK"
    return f"HTTP_{status_code}"


def safe_error(response: requests.Response) -> str | None:
    try:
        data = response.json()
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    error = data.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
        if isinstance(code, (str, int)) and isinstance(message, str):
            return f"code={code}; message={message[:300]}"
        if isinstance(message, str):
            return message[:300]
        if isinstance(code, (str, int)):
            return f"code={code}"
        return "error_object_present"
    if isinstance(error, str):
        return error[:300]
    return None


def check_connection(
    connection_id: str,
    key: str,
    model: str,
    tier: str,
) -> dict[str, Any]:
    session = create_session()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": TEST_MESSAGE}],
        "max_tokens": 4,
        "temperature": 0,
    }
    started = time.perf_counter()
    try:
        response = session.post(
            CHAT_URL,
            headers=headers,
            json=payload,
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
    except requests.ConnectTimeout:
        return {
            "connection_id": connection_id, "provider": "openrouter",
            "tier": tier, "model": model, "status": "CONNECT_TIMEOUT",
            "http_status": None, "latency_ms": None, "healthy": False,
            "completion_received": False, "error": f"Connection exceeded {CONNECT_TIMEOUT}s.",
            "checked_at": utc_now(),
        }
    except requests.ReadTimeout:
        return {
            "connection_id": connection_id, "provider": "openrouter",
            "tier": tier, "model": model, "status": "READ_TIMEOUT",
            "http_status": None, "latency_ms": None, "healthy": False,
            "completion_received": False, "error": f"Response exceeded {READ_TIMEOUT}s.",
            "checked_at": utc_now(),
        }
    except requests.Timeout:
        return {
            "connection_id": connection_id, "provider": "openrouter",
            "tier": tier, "model": model, "status": "TIMEOUT",
            "http_status": None, "latency_ms": None, ""healthy"": False,
            "completion_received": False, "error": "REQUEST_TIMEOUT",
            "checked_at": utc_now(),
        }
    except requests.ConnectionError as exc:
        return {
            "connection_id": connection_id, "provider": "openrouter",
            "tier": tier, "model": model, "status": "CONNECTION_ERROR",
            "http_status": None, "latency_ms": None, "healthy": False,
            "completion_received": False, "error": type(exc).__name__,
            "checked_at": utc_now(),
        }
    except requests.RequestException as exc:
        return {
            "connection_id": connection_id, "provider": "openrouter",
            "tier": tier, "model": model, "status": "REQUEST_ERROR",
            "http_status": None, "latency_ms": None, "healthy": False,
            "completion_received": False, "error": type(exc).__name__,
            "checked_at": utc_now(),
        }
    finally:
        session.close()

    result: dict[str, Any] = {
        "connection_id": connection_id,
        "provider": "openrouter",
        "tier": tier,
        "model": model,
        "status": classify_http_status(response.status_code),
        "http_status": response.status_code,
        "latency_ms": latency_ms,
        "healthy": False,
        "completion_received": False,
        "error": None,
        "checked_at": utc_now(),
    }

    if not response.ok:
        result["error"] = safe_error(response)
        return result

    try:
        data = response.json()
    except ValueError:
        result["status"] = "INVALID_JSON"
        result["error"] = "Response was not valid JSON."
        return result

    if not isinstance(data, dict):
        result["status"] = "INVALID_RESPONSE"
        result["error"] = "Response body was not a JSON object."
        return result

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        result["status"] = "INVALID_RESPONSE"
        result["error"] = "Response did not contain a valid choices array."
        return result

    first = choices[0]
    if not isinstance(first, dict):
        result["status"] = "INVALID_RESPONSE"
        result["error"] = "First choice was not a JSON object."
        return result

    message = first.get("message")
    content_ok = isinstance(message, dict) and isinstance(message.get("content"), str)
    text_ok = isinstance(first.get("text"), str)

    if not content_ok and not text_ok:
        result["status"] = "INVALID_RESPONSE"
        result["error"] = "First choice did not contain message or text output."
        return result

    result["status"] = "OK"
    result["healthy"] = True
    result["completion_received"] = True
    return result


def key_for_connection(keys: list[str], connection_id: str) -> str:
    try:
        number = int(connection_id.split("-", 1)[1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError(f"Invalid OpenRouter connection id: {connection_id}") from exc
    index = number - 1
    if index < 0 or index >= len(keys):
        raise RuntimeError(f"No OpenRouter key for {connection_id}")
    return keys[index]


def main() -> int:
    registry = validate_registry()
    leader = registry["architecture"]["leader"]
    keys = load_keys(KEY_FILE)

    primary_pool = list(leader["primary_pool"])
    failover_pool = list(leader["failover_pool"])
    expected_ids = list(dict.fromkeys(primary_pool + failover_pool))

    if len(keys) != len(expected_ids):
        raise RuntimeError(
            "Key count does not match unique OpenRouter leadership connections. "
            f"Keys={len(keys)}, Connections={len(expected_ids)}"
        )

    results: list[dict[str, Any]] = []
    healthy_primary: list[str] = []
    failed_primary: list[str] = []
    healthy_failover: list[str] = []
    failed_failover: list[str] = []

    print("=" * 70)
    print("OPENROUTER LEADER HEALTH CHECK")
    print("=" * 70)
    print(f"Primary model : {leader['primary_model']}")
    print(f"Failover model: {leader['failover_model']}")
    print(f"Connections   : {len(expected_ids)}")
    print("Project data  : NONE")
    print()

    for index, connection_id in enumerate(expected_ids, start=1):
        for tier, model, pool, healthy_pool, failed_pool in [
            ("Ultra", leader["primary_model"], primary_pool, healthy_primary, failed_primary),
            ("Super", leader["failover_model"], failover_pool, healthy_failover, failed_failover),
        ]:
            if connection_id not in pool:
                continue
            result = check_connection(
                connection_id=connection_id,
                key=key_for_connection(keys, connection_id),
                model=model,
                tier=tier,
            )
            results.append(result)
            if result["healthy"]:
                healthy_pool.append(connection_id)
                print(f"[{index:02d}/{len(expected_ids):02d}] {connection_id} {tier:<5} HEALTHY ✅ ({result['latency_ms']} ms)")
            else:
                failed_pool.append(connection_id)
                print(f"[{index:02d}/{len(expected_ids):02d}] {connection_id} {tier:<5} FAILED ❌ [{result['status']}]")

    output = {
        "checked_at": utc_now(),
        "provider": leader["provider"],
        "primary_model": leader["primary_model"],
        "failover_model": leader["failover_model"],
        "primary": {
            "healthy": healthy_primary,
            "failed": failed_primary,
            "healthy_connections": healthy_primary,
            "failed_connections": failed_primary,
        },
        "failover": {
            "healthy": healthy_failover,
            "failed": failed_failover,
            "healthy_connections": healthy_failover,
            "failed_connections": failed_failover,
        },
        "models": {
            leader["primary_model"]: {"healthy": healthy_primary, "failed": failed_primary},
            leader["failover_model"]: {"healthy": healthy_failover, "failed": failed_failover},
        },
        "results": {
            f"{item['connection_id']}:{item['tier']}": item
            for item in results
        },
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print(f"Saved: {OUTPUT_FILE.name}")
    print(f"Primary healthy : {len(healthy_primary)}")
    print(f"Primary failed  : {len(failed_primary)}")
    print(f"Failover healthy: {len(healthy_failover)}")
    print(f"Failover failed : {len(failed_failover)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
