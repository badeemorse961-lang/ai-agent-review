from __future__ import annotations

import json
import multiprocessing
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from leader_failover import (
    LeaderFailover,
    PROFILES_FILE,
)

from worker_router import (
    WorkerRouter,
    PROFILES_FILE as WORKER_PROFILES_FILE,
    HEALTH_FILE as WORKER_HEALTH_FILE,
)


BASE_DIR = Path(__file__).resolve().parent

OPENROUTER_KEYS_FILE = (
    BASE_DIR / "openrouter_keys.txt"
)

GROQ_KEYS_FILE = (
    BASE_DIR / "groq_keys.txt"
)

LEADER_HEALTH_FILE = (
    BASE_DIR / "leader_health.json"
)

RESULT_FILE = (
    BASE_DIR / "orchestration_smoke_result.json"
)

OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)

GROQ_URL = (
    "https://api.groq.com/openai/v1/chat/completions"
)

ULTRA_MODEL = (
    "nvidia/nemotron-3-ultra-550b-a55b:free"
)

SUPER_MODEL = (
    "nvidia/nemotron-3-super-120b-a12b:free"
)

WORKER_MODEL = (
    "openai/gpt-oss-120b"
)

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 15

LEADER_TOTAL_TIMEOUT = 35
WORKER_TOTAL_TIMEOUT = 30


# =============================================================
# General helpers
# =============================================================

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
            f"No keys found in {path.name}"
        )

    return keys


def load_json(
    path: Path,
) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing file: {path.name}"
        )

    return json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def save_json(
    path: Path,
    data: dict[str, Any],
) -> None:
    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
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


# =============================================================
# Connection mapping
# =============================================================

def connection_number(
    connection_id: str,
    prefix: str,
) -> int:
    if not connection_id.startswith(
        prefix
    ):
        raise ValueError(
            f"Invalid connection ID: "
            f"{connection_id}"
        )

    try:
        number = int(
            connection_id.split("-")[1]
        )
    except (
        ValueError,
        IndexError,
    ) as exc:
        raise ValueError(
            f"Invalid connection ID: "
            f"{connection_id}"
        ) from exc

    return number


def get_openrouter_key(
    keys: list[str],
    connection_id: str,
) -> str:
    number = connection_number(
        connection_id,
        "OR-",
    )

    index = number - 1

    if index < 0 or index >= len(keys):
        raise RuntimeError(
            f"No OpenRouter key for "
            f"{connection_id}"
        )

    return keys[index]


def get_groq_key(
    keys: list[str],
    connection_id: str,
) -> str:
    number = connection_number(
        connection_id,
        "GROQ-",
    )

    index = number - 1

    if index < 0 or index >= len(keys):
        raise RuntimeError(
            f"No Groq key for "
            f"{connection_id}"
        )

    return keys[index]


# =============================================================
# Safe response handling
# =============================================================

def extract_content(
    data: Any,
) -> str | None:

    if not isinstance(
        data,
        dict,
    ):
        return None

    choices = data.get(
        "choices"
    )

    if not isinstance(
        choices,
        list,
    ) or not choices:
        return None

    first = choices[0]

    if not isinstance(
        first,
        dict,
    ):
        return None

    message = first.get(
        "message"
    )

    if isinstance(
        message,
        dict,
    ):
        content = message.get(
            "content"
        )

        if isinstance(
            content,
            str,
        ):
            return content.strip()

    text = first.get(
        "text"
    )

    if isinstance(
        text,
        str,
    ):
        return text.strip()

    return None


def safe_error(
    response: requests.Response,
) -> str | None:

    try:
        data = response.json()
    except ValueError:
        return None

    if not isinstance(
        data,
        dict,
    ):
        return None

    error = data.get(
        "error"
    )

    if isinstance(
        error,
        dict,
    ):
        code = error.get(
            "code"
        )

        message = error.get(
            "message"
        )

        if isinstance(
            code,
            (str, int),
        ) and isinstance(
            message,
            str,
        ):
            return (
                f"code={code}; "
                f"message={message[:300]}"
            )

        if isinstance(
            message,
            str,
        ):
            return message[:300]

        return "error_object_present"

    if isinstance(
        error,
        str,
    ):
        return error[:300]

    return None


# =============================================================
# Network request
# =============================================================

def send_chat(
    url: str,
    key: str,
    model: str,
    messages: list[dict[str, str]],
) -> dict[str, Any]:

    session = create_session()

    headers = {
        "Authorization": (
            f"Bearer {key}"
        ),
        "Content-Type": (
            "application/json"
        ),
        "Accept": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0,
    }

    started = time.perf_counter()

    try:
        response = session.post(
            url,
            headers=headers,
            json=payload,
            timeout=(
                CONNECT_TIMEOUT,
                READ_TIMEOUT,
            ),
        )

        latency_ms = round(
            (
                time.perf_counter()
                - started
            ) * 1000,
            2,
        )

    except requests.ConnectTimeout:
        return {
            "success": False,
            "status": "CONNECT_TIMEOUT",
            "http_status": None,
            "latency_ms": None,
            "content": None,
            "error": (
                f"Connection exceeded "
                f"{CONNECT_TIMEOUT}s."
            ),
        }

    except requests.ReadTimeout:
        return {
            "success": False,
            "status": "READ_TIMEOUT",
            "http_status": None,
            "latency_ms": None,
            "content": None,
            "error": (
                f"Response exceeded "
                f"{READ_TIMEOUT}s."
            ),
        }

    except requests.Timeout:
        return {
            "success": False,
            "status": "TIMEOUT",
            "http_status": None,
            "latency_ms": None,
            "content": None,
            "error": "REQUEST_TIMEOUT",
        }

    except requests.ConnectionError as exc:
        return {
            "success": False,
            "status": "CONNECTION_ERROR",
            "http_status": None,
            "latency_ms": None,
            "content": None,
            "error": type(exc).__name__,
        }

    except requests.RequestException as exc:
        return {
            "success": False,
            "status": "REQUEST_ERROR",
            "http_status": None,
            "latency_ms": None,
            "content": None,
            "error": type(exc).__name__,
        }

    finally:
        session.close()

    if not response.ok:
        return {
            "success": False,
            "status": "HTTP_ERROR",
            "http_status": (
                response.status_code
            ),
            "latency_ms": latency_ms,
            "content": None,
            "error": safe_error(
                response
            ),
        }

    try:
        data = response.json()
    except ValueError:
        return {
            "success": False,
            "status": "INVALID_JSON",
            "http_status": (
                response.status_code
            ),
            "latency_ms": latency_ms,
            "content": None,
            "error": (
                "Response was not "
                "valid JSON."
            ),
        }

    content = extract_content(
        data
    )

    if not content:
        return {
            "success": False,
            "status": "INVALID_RESPONSE",
            "http_status": (
                response.status_code
            ),
            "latency_ms": latency_ms,
            "content": None,
            "error": (
                "No usable completion content."
            ),
        }

    return {
        "success": True,
        "status": "OK",
        "http_status": (
            response.status_code
        ),
        "latency_ms": latency_ms,
        "content": content,
        "error": None,
    }


# =============================================================
# Process-isolated request
# =============================================================

def request_process(
    result_queue: multiprocessing.Queue,
    url: str,
    key: str,
    model: str,
    messages: list[dict[str, str]],
) -> None:
    """
    Execute one API request in a separate process.

    The parent process can forcibly terminate this process
    if the total wall-clock budget is exceeded.
    """

    try:
        result = send_chat(
            url=url,
            key=key,
            model=model,
            messages=messages,
        )

        result_queue.put(
            result
        )

    except Exception as exc:
        result_queue.put(
            {
                "success": False,
                "status": "PROCESS_ERROR",
                "http_status": None,
                "latency_ms": None,
                "content": None,
                "error": (
                    f"{type(exc).__name__}: "
                    f"{str(exc)[:300]}"
                ),
            }
        )


def send_chat_with_total_timeout(
    url: str,
    key: str,
    model: str,
    messages: list[dict[str, str]],
    total_timeout: int,
) -> dict[str, Any]:

    queue: multiprocessing.Queue = (
        multiprocessing.Queue()
    )

    process = multiprocessing.Process(
        target=request_process,
        args=(
            queue,
            url,
            key,
            model,
            messages,
        ),
        daemon=True,
    )

    started = time.perf_counter()

    process.start()

    process.join(
        timeout=total_timeout
    )

    if process.is_alive():
        process.terminate()
        process.join(
            timeout=3
        )

        return {
            "success": False,
            "status": "TOTAL_TIMEOUT",
            "http_status": None,
            "latency_ms": round(
                (
                    time.perf_counter()
                    - started
                ) * 1000,
                2,
            ),
            "content": None,
            "error": (
                f"Total request exceeded "
                f"{total_timeout}s."
            ),
        }

    try:
        result = queue.get_nowait()
    except Exception:
        result = {
            "success": False,
            "status": "NO_PROCESS_RESULT",
            "http_status": None,
            "latency_ms": round(
                (
                    time.perf_counter()
                    - started
                ) * 1000,
                2,
            ),
            "content": None,
            "error": (
                "Request process ended "
                "without a result."
            ),
        }

    queue.close()
    queue.join_thread()

    return result


# =============================================================
# Local validation
# =============================================================

def validate_leader_plan(
    content: str,
) -> bool:

    normalized = content.lower()

    required_groups = [
        [
            "add",
            "addition",
        ],
        [
            "subtract",
            "subtraction",
            "-",
        ],
    ]

    return all(
        any(
            term in normalized
            for term in group
        )
        for group in required_groups
    )


def validate_worker_result(
    content: str,
) -> bool:

    normalized = content.lower()

    checks = 0

    if (
        "5" in normalized
        or "subtract" in normalized
    ):
        checks += 1

    if (
        "add" in normalized
        or "addition" in normalized
    ):
        checks += 1

    if (
        "return a + b" in normalized
        or "a + b" in normalized
    ):
        checks += 1

    return checks >= 2


# =============================================================
# Main orchestration test
# =============================================================

def main() -> int:

    print("=" * 70)
    print(
        "AI-AGENT ORCHESTRATION SMOKE TEST"
    )
    print("=" * 70)

    # ---------------------------------------------------------
    # Load keys and state
    # ---------------------------------------------------------

    openrouter_keys = load_keys(
        OPENROUTER_KEYS_FILE
    )

    groq_keys = load_keys(
        GROQ_KEYS_FILE
    )

    leader_health = load_json(
        LEADER_HEALTH_FILE
    )

    healthy_ultra = (
        leader_health[
            "primary"
        ][
            "healthy_connections"
        ]
    )

    healthy_super = (
        leader_health[
            "failover"
        ][
            "healthy_connections"
        ]
    )

    if not healthy_ultra:
        print(
            "No healthy Ultra leaders available."
        )
        return 1

    if not healthy_super:
        print(
            "No healthy Super leaders available."
        )
        return 1

    print()
    print(
        f"Healthy Ultra leaders : "
        f"{len(healthy_ultra)}"
    )

    print(
        f"Healthy Super leaders : "
        f"{len(healthy_super)}"
    )

    print(
        f"Healthy Groq workers  : "
        f"{len(groq_keys)}"
    )

    # ---------------------------------------------------------
    # Synthetic task
    # ---------------------------------------------------------

    task = (
        "Synthetic task only.\n"
        "\n"
        "Do not access or modify any files.\n"
        "\n"
        "A hypothetical Python function is:\n"
        "\n"
        "def add(a, b):\n"
        "    return a - b\n"
        "\n"
        "Identify the bug and propose the minimal "
        "logical correction. Then provide one concise "
        "instruction for a Coder worker.\n"
        "\n"
        "Do not claim that you changed a file."
    )

    leader_messages = [
        {
            "role": "system",
            "content": (
                "You are the central planning leader. "
                "Analyze the task, identify the smallest "
                "necessary correction, and delegate it. "
                "Do not edit files."
            ),
        },
        {
            "role": "user",
            "content": task,
        },
    ]

    # ---------------------------------------------------------
    # Phase 1: Leader
    # ---------------------------------------------------------

    print()
    print("-" * 70)
    print("PHASE 1: LEADER")
    print("-" * 70)

    leader_manager = LeaderFailover(
        PROFILES_FILE
    )

    # Select the first currently healthy Ultra.
    first_ultra = healthy_ultra[0]

    try:
        ultra_index = (
            leader_manager.primary_pool[
                "connections"
            ].index(first_ultra)
        )
    except ValueError:
        print(
            "Healthy Ultra connection is "
            "not present in leader pool."
        )
        return 1

    leader_manager.runtime[
        "primary_index"
    ] = ultra_index

    leader_manager.runtime[
        "active_tier"
    ] = "primary"

    leader_manager.runtime[
        "active_connection"
    ] = first_ultra

    leader_manager.runtime[
        "active_model"
    ] = ULTRA_MODEL

    leader_manager.runtime[
        "state"
    ] = "READY"

    leader_manager._save()

    active_connection = (
        leader_manager.current_connection()
    )

    active_model = (
        leader_manager.current_model()
    )

    print(
        f"Leader connection : "
        f"{active_connection}"
    )

    print(
        f"Leader model      : "
        f"{active_model}"
    )

    leader_key = get_openrouter_key(
        openrouter_keys,
        active_connection,
    )

    print(
        f"Leader timeout    : "
        f"{LEADER_TOTAL_TIMEOUT}s"
    )

    leader_result = (
        send_chat_with_total_timeout(
            url=OPENROUTER_URL,
            key=leader_key,
            model=active_model,
            messages=leader_messages,
            total_timeout=(
                LEADER_TOTAL_TIMEOUT
            ),
        )
    )

    # ---------------------------------------------------------
    # Leader failover
    # ---------------------------------------------------------

    if not leader_result["success"]:

        print(
            "Primary leader request failed ❌"
        )

        print(
            f"Reason: "
            f"{leader_result['status']}"
        )

        print(
            "Invoking model-aware "
            "leader failover..."
        )

        next_connection = (
            leader_manager.failover(
                reason=leader_result[
                    "status"
                ]
            )
        )

        if next_connection is None:
            print(
                "LEADER SAFE STOP ❌"
            )
            return 1

        active_connection = (
            leader_manager.current_connection()
        )

        active_model = (
            leader_manager.current_model()
        )

        print(
            f"Failover leader : "
            f"{active_connection}"
        )

        print(
            f"Failover model  : "
            f"{active_model}"
        )

        leader_key = get_openrouter_key(
            openrouter_keys,
            active_connection,
        )

        print(
            f"Failover timeout: "
            f"{LEADER_TOTAL_TIMEOUT}s"
        )

        leader_result = (
            send_chat_with_total_timeout(
                url=OPENROUTER_URL,
                key=leader_key,
                model=active_model,
                messages=leader_messages,
                total_timeout=(
                    LEADER_TOTAL_TIMEOUT
                ),
            )
        )

    if not leader_result["success"]:
        print(
            "Leader request failed "
            "after failover ❌"
        )

        print(
            f"Reason: "
            f"{leader_result['status']}"
        )

        leader_manager.reset()

        return 1

    leader_content = (
        leader_result["content"]
    )

    print(
        f"Leader response received ✅ "
        f"({leader_result['latency_ms']} ms)"
    )

    if not validate_leader_plan(
        leader_content
    ):
        print(
            "Leader output validation FAILED ❌"
        )

        leader_manager.reset()

        return 1

    print(
        "Leader output validation PASSED ✅"
    )

    # ---------------------------------------------------------
    # Phase 2: Worker Router
    # ---------------------------------------------------------

    print()
    print("-" * 70)
    print("PHASE 2: WORKER ROUTER")
    print("-" * 70)

    worker_router = WorkerRouter(
        WORKER_PROFILES_FILE,
        WORKER_HEALTH_FILE,
    )

    task_id = (
        "SMOKE-CODER-001"
    )

    acquisition = worker_router.acquire(
        role="coder",
        task_id=task_id,
    )

    print(
        f"Worker routing status : "
        f"{acquisition['status']}"
    )

    if acquisition["status"] != "ACQUIRED":
        print(
            "Worker Router could not "
            "acquire a Coder ❌"
        )

        leader_manager.reset()

        return 1

    worker_connection = (
        acquisition["connection"]
    )

    worker_model = (
        acquisition["model"]
    )

    print(
        f"Worker connection     : "
        f"{worker_connection}"
    )

    print(
        f"Worker model          : "
        f"{worker_model}"
    )

    print(
        f"Standby used          : "
        f"{acquisition['standby']}"
    )

    # ---------------------------------------------------------
    # Phase 3: Worker
    # ---------------------------------------------------------

    print()
    print("-" * 70)
    print("PHASE 3: GROQ CODER")
    print("-" * 70)

    worker_instruction = (
        "Synthetic reasoning task. "
        "Do not access or modify files.\n"
        "\n"
        "The hypothetical function is:\n"
        "\n"
        "def add(a, b):\n"
        "    return a - b\n"
        "\n"
        "Identify the exact bug and state "
        "the minimal corrected return expression."
    )

    worker_messages = [
        {
            "role": "system",
            "content": (
                "You are a specialist Coder worker. "
                "Only analyze and propose the requested "
                "change. Do not edit files."
            ),
        },
        {
            "role": "user",
            "content": worker_instruction,
        },
    ]

    groq_key = get_groq_key(
        groq_keys,
        worker_connection,
    )

    worker_result = (
        send_chat_with_total_timeout(
            url=GROQ_URL,
            key=groq_key,
            model=worker_model,
            messages=worker_messages,
            total_timeout=(
                WORKER_TOTAL_TIMEOUT
            ),
        )
    )

    if not worker_result["success"]:
        print(
            "Worker request failed ❌"
        )

        print(
            f"Reason: "
            f"{worker_result['status']}"
        )

        worker_router.mark_failed(
            role="coder",
            connection=worker_connection,
            reason=worker_result[
                "status"
            ],
        )

        worker_router._persist()

        leader_manager.reset()

        return 1

    worker_content = (
        worker_result["content"]
    )

    print(
        f"Worker response received ✅ "
        f"({worker_result['latency_ms']} ms)"
    )

    # ---------------------------------------------------------
    # Phase 4: Local validation
    # ---------------------------------------------------------

    print()
    print("-" * 70)
    print("PHASE 4: LOCAL VALIDATION")
    print("-" * 70)

    if not validate_worker_result(
        worker_content
    ):
        print(
            "Worker output validation FAILED ❌"
        )

        worker_router.release(
            worker_connection
        )

        leader_manager.reset()

        return 1

    print(
        "Worker output validation PASSED ✅"
    )

    # ---------------------------------------------------------
    # Release worker lease
    # ---------------------------------------------------------

    released = worker_router.release(
        worker_connection
    )

    if not released:
        print(
            "Worker lease release FAILED ❌"
        )

        leader_manager.reset()

        return 1

    print(
        "Worker lease released ✅"
    )

    # ---------------------------------------------------------
    # Final result
    # ---------------------------------------------------------

    result = {
        "version": 2,
        "completed_at": utc_now(),

        "task_type": (
            "synthetic_orchestration_smoke_test"
        ),

        "project_files_sent": False,

        "leader": {
            "connection": active_connection,
            "model": active_model,
            "success": True,
            "latency_ms": leader_result[
                "latency_ms"
            ],
            "validated": True,
        },

        "worker": {
            "role": "coder",
            "connection": worker_connection,
            "model": worker_model,
            "standby": acquisition[
                "standby"
            ],
            "success": True,
            "latency_ms": worker_result[
                "latency_ms"
            ],
            "validated": True,
            "lease_released": True,
        },

        "local_validation": {
            "leader_plan": True,
            "worker_result": True,
        },

        "overall": "PASSED",
    }

    save_json(
        RESULT_FILE,
        result,
    )

    leader_manager.reset()

    print()
    print("=" * 70)
    print(
        "ORCHESTRATION SMOKE TEST PASSED ✅"
    )
    print("=" * 70)

    print()
    print(
        "Leader -> Worker -> Validation"
    )

    print(
        "Project files sent : NO"
    )

    print(
        f"Result saved      : "
        f"{RESULT_FILE.name}"
    )

    print("=" * 70)

    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(
        main()
    )