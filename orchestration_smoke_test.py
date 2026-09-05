from __future__ import annotations

import json
import multiprocessing
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter

from config_registry import validate_registry
from leader_router import LeaderLease, LeaderRouter, LeaderUnavailable
from worker_router import NoWorkerAvailable, WorkerLease, WorkerRouter


BASE_DIR = Path(__file__).resolve().parent

OPENROUTER_KEYS_FILE = BASE_DIR / "openrouter_keys.txt"
GROQ_KEYS_FILE = BASE_DIR / "groq_keys.txt"
LEADER_HEALTH_FILE = BASE_DIR / "leader_health.json"
WORKER_HEALTH_FILE = BASE_DIR / "groq_worker_health.json"
RESULT_FILE = BASE_DIR / "orchestration_smoke_result.json"

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 15
LEADER_TOTAL_TIMEOUT = 35
WORKER_TOTAL_TIMEOUT = 30


# =============================================================
# General helpers
# =============================================================


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_keys(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing key file: {path.name}")

    keys = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    if not keys:
        raise RuntimeError(f"No keys found in {path.name}")

    return keys


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path.name}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON root must be an object: {path.name}")

    return payload


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def create_session() -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=0)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


# =============================================================
# Connection key mapping
# =============================================================


def connection_number(connection_id: str, prefix: str) -> int:
    if not connection_id.startswith(prefix):
        raise ValueError(f"Invalid connection ID: {connection_id}")

    try:
        return int(connection_id.split("-", 1)[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"Invalid connection ID: {connection_id}") from exc


def key_for_connection(keys: list[str], connection_id: str, prefix: str) -> str:
    number = connection_number(connection_id, prefix)
    index = number - 1

    if index < 0 or index >= len(keys):
        raise RuntimeError(f"No key available for {connection_id}")

    return keys[index]


# =============================================================
# Safe response handling
# =============================================================


def extract_content(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None

    first = choices[0]
    if not isinstance(first, dict):
        return None

    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

    text = first.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    return None


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
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
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
            timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
        )
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
    except requests.ConnectTimeout:
        return {
            "success": False,
            "status": "CONNECT_TIMEOUT",
            "http_status": None,
            "latency_ms": None,
            "content": None,
            "error": f"Connection exceeded {CONNECT_TIMEOUT}s.",
        }
    except requests.ReadTimeout:
        return {
            "success": False,
            "status": "READ_TIMEOUT",
            "http_status": None,
            "latency_ms": None,
            "content": None,
            "error": f"Response exceeded {READ_TIMEOUT}s.",
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
            "http_status": response.status_code,
            "latency_ms": latency_ms,
            "content": None,
            "error": safe_error(response),
        }

    try:
        data = response.json()
    except ValueError:
        return {
            "success": False,
            "status": "INVALID_JSON",
            "http_status": response.status_code,
            "latency_ms": latency_ms,
            "content": None,
            "error": "Response was not valid JSON.",
        }

    content = extract_content(data)
    if not content:
        return {
            "success": False,
            "status": "INVALID_RESPONSE",
            "http_status": response.status_code,
            "latency_ms": latency_ms,
            "content": None,
            "error": "No usable completion content.",
        }

    return {
        "success": True,
        "status": "OK",
        "http_status": response.status_code,
        "latency_ms": latency_ms,
        "content": content,
        "error": None,
    }


def request_process(
    result_queue: multiprocessing.Queue,
    url: str,
    key: str,
    model: str,
    messages: list[dict[str, str]],
) -> None:
    try:
        result_queue.put(
            send_chat(
                url=url,
                key=key,
                model=model,
                messages=messages,
            )
        )
    except Exception as exc:
        result_queue.put(
            {
                "success": False,
                "status": "PROCESS_ERROR",
                "http_status": None,
                "latency_ms": None,
                "content": None,
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }
        )


def send_chat_with_total_timeout(
    url: str,
    key: str,
    model: str,
    messages: list[dict[str, str]],
    total_timeout: int,
) -> dict[str, Any]:
    queue: multiprocessing.Queue = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=request_process,
        args=(queue, url, key, model, messages),
        daemon=True,
    )

    started = time.perf_counter()
    process.start()
    process.join(timeout=total_timeout)

    if process.is_alive():
        process.terminate()
        process.join(timeout=3)
        queue.close()
        queue.join_thread()
        return {
            "success": False,
            "status": "TOTAL_TIMEOUT",
            "http_status": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "content": None,
            "error": f"Total request exceeded {total_timeout}s.",
        }

    try:
        result = queue.get_nowait()
    except Exception:
        result = {
            "success": False,
            "status": "NO_PROCESS_RESULT",
            "http_status": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "content": None,
            "error": "Request process ended without a result.",
        }

    queue.close()
    queue.join_thread()
    return result


# =============================================================
# Local validation
# =============================================================


def validate_leader_plan(content: str) -> bool:
    normalized = content.lower()
    required_groups = [
        ("add", "addition"),
        ("subtract", "subtraction", "-"),
    ]
    return all(
        any(term in normalized for term in group)
        for group in required_groups
    )


def validate_worker_result(content: str) -> bool:
    normalized = content.lower()
    checks = 0

    if "5" in normalized or "subtract" in normalized:
        checks += 1
    if "add" in normalized or "addition" in normalized:
        checks += 1
    if "return a + b" in normalized or "a + b" in normalized:
        checks += 1

    return checks >= 2


# =============================================================
# Retry / failover helpers
# =============================================================


def acquire_leader_until_success(
    router: LeaderRouter,
    key_map: list[str],
    task_id: str,
    messages: list[dict[str, str]],
) -> tuple[LeaderLease, dict[str, Any], int]:
    attempts = 0

    while True:
        try:
            lease = router.acquire(task_id)
        except LeaderUnavailable:
            raise

        attempts += 1
        key = key_for_connection(key_map, lease.account_id, "OR-")
        result = send_chat_with_total_timeout(
            url=OPENROUTER_URL,
            key=key,
            model=lease.model,
            messages=messages,
            total_timeout=LEADER_TOTAL_TIMEOUT,
        )

        if result["success"]:
            return lease, result, attempts

        router.fail_current_leader(
            task_id,
            reason=result["status"],
        )


def acquire_worker_until_success(
    router: WorkerRouter,
    key_map: list[str],
    role: str,
    task_id: str,
    messages: list[dict[str, str]],
) -> tuple[WorkerLease, dict[str, Any], int]:
    attempts = 0

    while True:
        try:
            lease = router.acquire(role=role, task_id=task_id)
        except NoWorkerAvailable:
            raise

        attempts += 1
        key = key_for_connection(key_map, lease.worker_id, "GROQ-")
        result = send_chat_with_total_timeout(
            url=GROQ_URL,
            key=key,
            model=router.model,
            messages=messages,
            total_timeout=WORKER_TOTAL_TIMEOUT,
        )

        if result["success"]:
            return lease, result, attempts

        router.fail_current_worker(task_id)


# =============================================================
# Main orchestration test
# =============================================================


def main() -> int:
    registry = validate_registry()
    leader_cfg = registry["architecture"]["leader"]
    worker_cfg = registry["architecture"]["workers"]

    openrouter_keys = load_keys(OPENROUTER_KEYS_FILE)
    groq_keys = load_keys(GROQ_KEYS_FILE)
    leader_health = load_json(LEADER_HEALTH_FILE)

    primary_health = leader_health.get("primary", {})
    failover_health = leader_health.get("failover", {})
    healthy_ultra = primary_health.get("healthy_connections")
    healthy_super = failover_health.get("healthy_connections")

    if not isinstance(healthy_ultra, list):
        healthy_ultra = primary_health.get("healthy", [])
    if not isinstance(healthy_super, list):
        healthy_super = failover_health.get("healthy", [])

    if not healthy_ultra:
        print("No healthy Ultra leaders available.")
        return 1
    if not healthy_super:
        print("No healthy Super leaders available.")
        return 1

    worker_pools = worker_cfg.get("roles", {})
    if not isinstance(worker_pools, dict) or not worker_pools.get("coder"):
        print("No configured coder worker pool available.")
        return 1

    print("=" * 70)
    print("AI-AGENT ORCHESTRATION SMOKE TEST")
    print("=" * 70)
    print()
    print(f"Healthy Ultra leaders : {len(healthy_ultra)}")
    print(f"Healthy Super leaders : {len(healthy_super)}")
    print(f"Configured Groq workers: {sum(len(pool) for pool in worker_pools.values() if isinstance(pool, list))}")

    task = (
        "Synthetic task only.\n\n"
        "Do not access or modify any files.\n\n"
        "A hypothetical Python function is:\n\n"
        "def add(a, b):\n"
        "    return a - b\n\n"
        "Identify the bug and propose the minimal logical correction. "
        "Then provide one concise instruction for a Coder worker.\n\n"
        "Do not claim that you changed a file."
    )

    leader_messages = [
        {
            "role": "system",
            "content": (
                "You are the central planning leader. Analyze the task, "
                "identify the smallest necessary correction, and delegate it. "
                "Do not edit files."
            ),
        },
        {"role": "user", "content": task},
    ]

    worker_messages = [
        {
            "role": "system",
            "content": (
                "You are a specialist Coder worker. Only analyze and propose "
                "the requested change. Do not edit files."
            ),
        },
        {
            "role": "user",
            "content": (
                "Synthetic reasoning task. Do not access or modify files.\n\n"
                "The hypothetical function is:\n\n"
                "def add(a, b):\n"
                "    return a - b\n\n"
                "Identify the exact bug and state the minimal corrected return expression."
            ),
        },
    ]

    # ---------------------------------------------------------
    # Phase 1: Leader with runtime failover
    # ---------------------------------------------------------

    print()
    print("-" * 70)
    print("PHASE 1: LEADER")
    print("-" * 70)

    leader_router = LeaderRouter()
    leader_task_id = "SMOKE-LEADER-001"

    try:
        leader_lease, leader_result, leader_attempts = acquire_leader_until_success(
            router=leader_router,
            key_map=openrouter_keys,
            task_id=leader_task_id,
            messages=leader_messages,
        )
    except LeaderUnavailable:
        print("LEADER SAFE STOP: no usable leader remained.")
        return 1

    print(f"Leader connection : {leader_lease.account_id}")
    print(f"Leader model      : {leader_lease.model}")
    print(f"Leader tier       : {leader_lease.tier}")
    print(f"Leader attempts   : {leader_attempts}")
    print(f"Leader response   : {leader_result['latency_ms']} ms")

    leader_content = leader_result["content"]
    if not isinstance(leader_content, str) or not validate_leader_plan(leader_content):
        leader_router.release(leader_task_id)
        leader_router.reset_runtime()
        print("Leader output validation FAILED.")
        return 1

    print("Leader output validation PASSED ✅")
    leader_router.release(leader_task_id)

    # ---------------------------------------------------------
    # Phase 2: Worker with runtime failover
    # ---------------------------------------------------------

    print()
    print("-" * 70)
    print("PHASE 2: WORKER ROUTER")
    print("-" * 70)

    worker_router = WorkerRouter()
    worker_task_id = "SMOKE-CODER-001"

    try:
        worker_lease, worker_result, worker_attempts = acquire_worker_until_success(
            router=worker_router,
            key_map=groq_keys,
            role="coder",
            task_id=worker_task_id,
            messages=worker_messages,
        )
    except NoWorkerAvailable:
        leader_router.reset_runtime()
        print("WORKER SAFE STOP: no usable coder/standby remained.")
        return 1

    print(f"Worker connection : {worker_lease.worker_id}")
    print(f"Worker model      : {worker_router.model}")
    print(f"Standby used      : {worker_lease.standby}")
    print(f"Worker attempts   : {worker_attempts}")
    print(f"Worker response   : {worker_result['latency_ms']} ms")

    worker_content = worker_result["content"]
    if not isinstance(worker_content, str) or not validate_worker_result(worker_content):
        worker_router.release(worker_task_id)
        worker_router.reset_runtime()
        print("Worker output validation FAILED.")
        return 1

    print("Worker output validation PASSED ✅")

    worker_router.release(worker_task_id)
    worker_router.reset_runtime()
    leader_router.reset_runtime()

    result = {
        "version": 3,
        "completed_at": utc_now(),
        "task_type": "synthetic_orchestration_smoke_test",
        "project_files_sent": False,
        "registry_driven": True,
        "runtime_failover_enabled": True,
        "leader": {
            "connection": leader_lease.account_id,
            "model": leader_lease.model,
            "tier": leader_lease.tier,
            "success": True,
            "attempts": leader_attempts,
            "latency_ms": leader_result["latency_ms"],
            "validated": True,
        },
        "worker": {
            "role": worker_lease.role,
            "connection": worker_lease.worker_id,
            "model": worker_router.model,
            "standby": worker_lease.standby,
            "success": True,
            "attempts": worker_attempts,
            "latency_ms": worker_result["latency_ms"],
            "validated": True,
            "lease_released": True,
        },
        "local_validation": {
            "leader_plan": True,
            "worker_result": True,
        },
        "overall": "PASSED",
    }

    save_json(RESULT_FILE, result)

    print()
    print("=" * 70)
    print("ORCHESTRATION SMOKE TEST PASSED ✅")
    print("=" * 70)
    print()
    print("Leader -> Worker -> Validation")
    print("Runtime failures -> alternate connection/model")
    print("Project files sent : NO")
    print(f"Result saved      : {RESULT_FILE.name}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
