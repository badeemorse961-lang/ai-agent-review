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
KEY_FILE = BASE_DIR / "groq_keys.txt"
OUTPUT_FILE = BASE_DIR / "groq_worker_health.json"
CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 20
TEST_MESSAGE = "Health check only. Reply with exactly: OK"
GOOD_STATUSES = {"HEALTHY", "READY", "VALID", "OK", "AVAILABLE"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_keys(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing key file: {path.name}")
    keys = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not keys:
        raise RuntimeError("No Groq keys were found.")
    return keys


def key_for_connection(keys: list[str], connection_id: str) -> str:
    try:
        number = int(connection_id.split("-", 1)[1])
    except (IndexError, ValueError) as exc:
        raise RuntimeError(f"Invalid Groq worker id: {connection_id}") from exc
    index = number - 1
    if index < 0 or index >= len(keys):
        raise RuntimeError(f"No Groq key for {connection_id}")
    return keys[index]


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


def failed_result(connection_id: str, model: str, status: str, error: str | None) -> dict[str, Any]:
    return {
        "connection_id": connection_id,
        "provider": "groq",
        "model": model,
        "status": status,
        "http_status": None,
        "latency_ms": None,
        "healthy": False,
        "completion_received": False,
        "error": error,
        "checked_at": utc_now(),
    }


def check_connection(connection_id: str, key: str, model: str) -> dict[str, Any]:
    session = create_session()
    started = time.perf_counter()
    try:
        response = session.post(
            CHAT_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": TEST_MESSAGE}],
                "max_tokens": 4,
                "temperature": 0,
            },
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
    except requests.ConnectTimeout:
        return failed_result(connection_id, model, "CONNECT_TIMEOUT", f"Connection exceeded {CONNECT_TIMEOUT}s")
    except requests.ReadTimeout:
        return failed_result(connection_id, model, "READ_TIMEOUT", f"Response exceeded {READ_TIMEOUT}s")
    except requests.Timeout:
        return failed_result(connection_id, model, "TIMEOUT", "REQUEST_TIMEOUT")
    except requests.ConnectionError as exc:
        return failed_result(connection_id, model, "CONNECTION_ERROR", type(exc).__name__)
    except requests.RequestException as exc:
        return failed_result(connection_id, model, "REQUEST_ERROR", type(exc).__name__)
    finally:
        session.close()

    result: dict[str, Any] = {
        "connection_id": connection_id,
        "provider": "groq",
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
        result["error"] = "Response was not valid JSON"
        return result

    if not isinstance(data, dict):
        result["status"] = "INVALID_RESPONSE"
        result["error"] = "Response body was not a JSON object"
        return result

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        result["status"] = "INVALID_RESPONSE"
        result["error"] = "Response did not contain a valid choices array"
        return result

    first = choices[0]
    if not isinstance(first, dict):
        result["status"] = "INVALID_RESPONSE"
        result["error"] = "First choice was not a JSON object"
        return result

    message = first.get("message")
    content_ok = isinstance(message, dict) and isinstance(message.get("content"), str)
    text_ok = isinstance(first.get("text"), str)
    if not content_ok and not text_ok:
        result["status"] = "INVALID_RESPONSE"
        result["error"] = "First choice did not contain message or text output"
        return result

    result["status"] = "OK"
    result["healthy"] = True
    result["completion_received"] = True
    return result


def main() -> int:
    registry = validate_registry()
    workers = registry["architecture"]["workers"]
    model = workers["model"]
    roles = workers["roles"]
    connection_ids = list(dict.fromkeys(
        worker_id
        for pool in roles.values()
        for worker_id in pool
    ))

    keys = load_keys(KEY_FILE)
    if len(keys) != len(connection_ids):
        raise RuntimeError(
            "Key count does not match unique Groq worker connections. "
            f"Keys={len(keys)}, Connections={len(connection_ids)}"
        )

    print("=" * 70)
    print("GROQ WORKER HEALTH CHECK")
    print("=" * 70)
    print(f"Worker model: {model}")
    print(f"Workers     : {len(connection_ids)}")
    print("Project data: NONE")
    print()

    results: list[dict[str, Any]] = []
    healthy: list[str] = []
    failed: list[str] = []

    for index, connection_id in enumerate(connection_ids, start=1):
        result = check_connection(
            connection_id,
            key_for_connection(keys, connection_id),
            model,
        )
        results.append(result)
        if result["healthy"]:
            healthy.append(connection_id)
            print(f"[{index:02d}/{len(connection_ids):02d}] {connection_id} HEALTHY ✅ ({result['latency_ms']} ms)")
        else:
            failed.append(connection_id)
            print(f"[{index:02d}/{len(connection_ids):02d}] {connection_id} FAILED ❌ [{result['status']}]")

    output = {
        "checked_at": utc_now(),
        "provider": workers["provider"],
        "model": model,
        "healthy": healthy,
        "failed": failed,
        "results": {item["connection_id"]: item for item in results},
    }
    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print()
    print(f"Saved: {OUTPUT_FILE.name}")
    print(f"Healthy: {len(healthy)}")
    print(f"Failed : {len(failed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
