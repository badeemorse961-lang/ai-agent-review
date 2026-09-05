from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter


BASE_DIR = Path(__file__).resolve().parent

KEY_FILE = BASE_DIR / "groq_keys.txt"
ROLES_FILE = BASE_DIR / "roles.json"
OUTPUT_FILE = BASE_DIR / "groq_worker_health.json"

CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"

WORKER_MODEL = "openai/gpt-oss-120b"

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 20

TEST_MESSAGE = (
    "Health check only. Reply with exactly: OK"
)


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def load_keys(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing key file: {path.name}"
        )

    keys = [
        line.strip()
        for line in path.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    if not keys:
        raise RuntimeError(
            "No Groq keys were found."
        )

    return keys


def load_roles(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing roles file: {path.name}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def create_session() -> requests.Session:
    session = requests.Session()

    adapter = HTTPAdapter(
        max_retries=0
    )

    session.mount(
        "https://",
        adapter
    )

    session.mount(
        "http://",
        adapter
    )

    return session


def classify_http_status(
    status_code: int,
) -> str:
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


def safe_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [
            str(key)
            for key in value.keys()
        ]

    return []


def inspect_response_shape(
    response: requests.Response,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content_type": response.headers.get(
            "content-type"
        ),
        "json_object": False,
        "top_level_keys": [],
        "has_choices": False,
        "choices_type": None,
        "choices_count": None,
        "has_error": False,
        "error_type": None,
        "error_keys": [],
        "has_output": False,
    }

    try:
        data = response.json()
    except ValueError:
        result["parse_error"] = (
            "response_is_not_valid_json"
        )
        return result

    if not isinstance(data, dict):
        result["parse_error"] = (
            "json_body_is_not_an_object"
        )
        return result

    result["json_object"] = True
    result["top_level_keys"] = safe_keys(data)

    choices = data.get("choices")

    if choices is not None:
        result["has_choices"] = True
        result["choices_type"] = type(
            choices
        ).__name__

        if isinstance(choices, list):
            result["choices_count"] = len(
                choices
            )

            if choices:
                first = choices[0]

                if isinstance(first, dict):
                    result["first_choice_keys"] = (
                        safe_keys(first)
                    )

                    message = first.get(
                        "message"
                    )

                    if isinstance(
                        message,
                        dict,
                    ):
                        result["message_keys"] = (
                            safe_keys(message)
                        )

                        if "content" in message:
                            result["has_output"] = True

                    if "text" in first:
                        result["has_output"] = True

    error = data.get("error")

    if error is not None:
        result["has_error"] = True
        result["error_type"] = type(
            error
        ).__name__

        if isinstance(error, dict):
            result["error_keys"] = safe_keys(
                error
            )

    return result


def extract_safe_error(
    response: requests.Response,
) -> str | None:
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

        if isinstance(code, (str, int)):
            if isinstance(message, str):
                return (
                    f"code={code}; "
                    f"message={message[:300]}"
                )

            return f"code={code}"

        if isinstance(message, str):
            return message[:300]

        return "error_object_present"

    if isinstance(error, str):
        return error[:300]

    return None


def check_connection(
    connection_id: str,
    key: str,
) -> dict[str, Any]:

    session = create_session()

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    payload = {
        "model": WORKER_MODEL,
        "messages": [
            {
                "role": "user",
                "content": TEST_MESSAGE,
            }
        ],
        "max_tokens": 4,
        "temperature": 0,
    }

    started = time.perf_counter()

    try:
        response = session.post(
            CHAT_URL,
            headers=headers,
            json=payload,
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT,
            ),
        )

        elapsed_ms = round(
            (
                time.perf_counter()
                - started
            ) * 1000,
            2,
        )

    except requests.ConnectTimeout:
        return {
            "connection_id": connection_id,
            "provider": "groq",
            "model": WORKER_MODEL,
            "status": "CONNECT_TIMEOUT",
            "http_status": None,
            "latency_ms": None,
            "healthy": False,
            "completion_received": False,
            "error": (
                f"Connection exceeded "
                f"{CONNECT_TIMEOUT}s."
            ),
            "diagnostics": None,
            "checked_at": utc_now(),
        }

    except requests.ReadTimeout:
        return {
            "connection_id": connection_id,
            "provider": "groq",
            "model": WORKER_MODEL,
            "status": "READ_TIMEOUT",
            "http_status": None,
            "latency_ms": None,
            "healthy": False,
            "completion_received": False,
            "error": (
                f"Response exceeded "
                f"{READ_TIMEOUT}s."
            ),
            "diagnostics": None,
            "checked_at": utc_now(),
        }

    except requests.Timeout:
        return {
            "connection_id": connection_id,
            "provider": "groq",
            "model": WORKER_MODEL,
            "status": "TIMEOUT",
            "http_status": None,
            "latency_ms": None,
            "healthy": False,
            "completion_received": False,
            "error": "REQUEST_TIMEOUT",
            "diagnostics": None,
            "checked_at": utc_now(),
        }

    except requests.ConnectionError as exc:
        return {
            "connection_id": connection_id,
            "provider": "groq",
            "model": WORKER_MODEL,
            "status": "CONNECTION_ERROR",
            "http_status": None,
            "latency_ms": None,
            "healthy": False,
            "completion_received": False,
            "error": type(exc).__name__,
            "diagnostics": None,
            "checked_at": utc_now(),
        }

    except requests.RequestException as exc:
        return {
            "connection_id": connection_id,
            "provider": "groq",
            "model": WORKER_MODEL,
            "status": "REQUEST_ERROR",
            "http_status": None,
            "latency_ms": None,
            "healthy": False,
            "completion_received": False,
            "error": type(exc).__name__,
            "diagnostics": None,
            "checked_at": utc_now(),
        }

    finally:
        session.close()

    result: dict[str, Any] = {
        "connection_id": connection_id,
        "provider": "groq",
        "model": WORKER_MODEL,
        "status": classify_http_status(
            response.status_code
        ),
        "http_status": response.status_code,
        "latency_ms": elapsed_ms,
        "healthy": False,
        "completion_received": False,
        "error": None,
        "diagnostics": None,
        "checked_at": utc_now(),
    }

    if not response.ok:
        result["error"] = extract_safe_error(
            response
        )

        result["diagnostics"] = (
            inspect_response_shape(
                response
            )
        )

        return result

    try:
        data = response.json()
    except ValueError:
        result["status"] = "INVALID_JSON"
        result["error"] = (
            "Response was not valid JSON."
        )

        result["diagnostics"] = {
            "content_type": response.headers.get(
                "content-type"
            ),
            "json_object": False,
        }

        return result

    if not isinstance(
        data,
        dict,
    ):
        result["status"] = "INVALID_RESPONSE"
        result["error"] = (
            "Response body was not "
            "a JSON object."
        )

        result["diagnostics"] = (
            inspect_response_shape(
                response
            )
        )

        return result

    choices = data.get("choices")

    if not isinstance(
        choices,
        list,
    ) or not choices:
        result["status"] = "INVALID_RESPONSE"
        result["error"] = (
            "Response did not contain "
            "a valid choices array."
        )

        result["diagnostics"] = (
            inspect_response_shape(
                response
            )
        )

        return result

    first_choice = choices[0]

    if not isinstance(
        first_choice,
        dict,
    ):
        result["status"] = "INVALID_RESPONSE"
        result["error"] = (
            "First choice was not "
            "a JSON object."
        )

        result["diagnostics"] = (
            inspect_response_shape(
                response
            )
        )

        return result

    has_message = isinstance(
        first_choice.get("message"),
        dict,
    )

    has_text = isinstance(
        first_choice.get("text"),
        str,
    )

    if not has_message and not has_text:
        result["status"] = "INVALID_RESPONSE"
        result["error"] = (
            "First choice did not contain "
            "message or text output."
        )

        result["diagnostics"] = (
            inspect_response_shape(
                response
            )
        )

        return result

    result["completion_received"] = True
    result["healthy"] = True
    result["status"] = "OK"

    return result


def print_result(
    index: int,
    total: int,
    connection_id: str,
    result: dict[str, Any],
) -> None:

    print(
        f"[{index:02d}/{total:02d}] "
        f"{connection_id} ... ",
        end="",
        flush=True,
    )

    if result["healthy"]:
        print(
            f"HEALTHY ✅ "
            f"({result['latency_ms']} ms)"
        )
        return

    status = result.get(
        "status"
    )

    error = result.get(
        "error"
    )

    print(
        f"FAILED ❌ "
        f"[{status}]"
        + (
            f" - {error}"
            if error
            else ""
        )
    )

    diagnostics = result.get(
        "diagnostics"
    )

    if diagnostics:
        print(
            "         "
            f"HTTP={result.get('http_status')} "
            f"JSON={diagnostics.get('json_object')} "
            f"KEYS={diagnostics.get('top_level_keys')} "
            f"HAS_CHOICES={diagnostics.get('has_choices')} "
            f"CHOICES_COUNT={diagnostics.get('choices_count')} "
            f"HAS_ERROR={diagnostics.get('has_error')}"
        )


def main() -> int:
    print("=" * 70)
    print("GROQ WORKER HEALTH CHECK")
    print("=" * 70)

    keys = load_keys(
        KEY_FILE
    )

    roles = load_roles(
        ROLES_FILE
    )

    worker_roles = [
        "coder",
        "debugger",
        "tester",
        "architect",
        "reviewer",
        "standby",
    ]

    expected_worker_connections = []

    for role_name in worker_roles:
        role = roles["roles"].get(
            role_name
        )

        if not role:
            raise RuntimeError(
                f"Missing worker role: {role_name}"
            )

        expected_worker_connections.extend(
            role.get("connections", [])
        )

    expected_worker_connections = list(
        dict.fromkeys(
            expected_worker_connections
        )
    )

    if len(keys) != len(
        expected_worker_connections
    ):
        raise RuntimeError(
            "Key count does not match "
            "Groq worker connections. "
            f"Keys={len(keys)}, "
            f"Workers="
            f"{len(expected_worker_connections)}"
        )

    print()
    print(
        f"Connections to test : "
        f"{len(keys)}"
    )

    print(
        f"Worker model        : "
        f"{WORKER_MODEL}"
    )

    print(
        "Requests per account: 1"
    )

    print(
        "Project data sent   : NONE"
    )

    print(
        f"Connect timeout     : "
        f"{CONNECT_TIMEOUT}s"
    )

    print(
        f"Read timeout        : "
        f"{READ_TIMEOUT}s"
    )

    print()

    results = []

    healthy = []
    unhealthy = []

    for index, key in enumerate(
        keys,
        start=1,
    ):
        connection_id = (
            f"GROQ-{index:02d}"
        )

        result = check_connection(
            connection_id=connection_id,
            key=key,
        )

        results.append(
            result
        )

        print_result(
            index=index,
            total=len(keys),
            connection_id=connection_id,
            result=result,
        )

        if result["healthy"]:
            healthy.append(
                connection_id
            )
        else:
            unhealthy.append(
                connection_id
            )

    role_membership = {}

    for role_name in worker_roles:
        role_membership[role_name] = (
            roles["roles"][role_name][
                "connections"
            ]
        )

    output = {
        "version": 1,
        "checked_at": utc_now(),
        "provider": "groq",
        "worker_model": WORKER_MODEL,

        "healthy_connections": healthy,
        "unhealthy_connections": unhealthy,

        "healthy_count": len(
            healthy
        ),
        "unhealthy_count": len(
            unhealthy
        ),

        "worker_pool_available": bool(
            healthy
        ),

        "role_membership": role_membership,

        "connections": results,
    }

    OUTPUT_FILE.write_text(
        json.dumps(
            output,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print()
    print("=" * 70)
    print("GROQ WORKER HEALTH SUMMARY")
    print("=" * 70)

    print()

    print(
        f"Healthy   : "
        f"{len(healthy)}/{len(keys)}"
    )

    print(
        f"Unhealthy : "
        f"{len(unhealthy)}/{len(keys)}"
    )

    print()

    if healthy:
        print(
            "Healthy pool:"
        )

        print(
            "  "
            + ", ".join(
                healthy
            )
        )

    if unhealthy:
        print()

        print(
            "Unhealthy:"
        )

        print(
            "  "
            + ", ".join(
                unhealthy
            )
        )

    print()

    print(
        f"Saved: {OUTPUT_FILE.name}"
    )

    print()
    print(
        "No API keys were printed."
    )

    print(
        "No project files were sent."
    )

    print("=" * 70)

    if not healthy:
        print(
            "RESULT: GROQ WORKER "
            "POOL UNAVAILABLE ❌"
        )
        return 1

    print(
        "RESULT: GROQ WORKER "
        "POOL AVAILABLE ✅"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )