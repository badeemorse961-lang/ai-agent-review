from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from config_registry import REGISTRY_FILE, RegistryError, validate_registry


BASE_DIR = Path(__file__).resolve().parent
WORKER_HEALTH_FILE = BASE_DIR / "groq_worker_health.json"
STATE_FILE = BASE_DIR / "worker_router_state.json"

# Compatibility-only names. They are never read for routing configuration.
WORKER_PROFILES_FILE = BASE_DIR / "worker_profiles.json"
ROLES_FILE = BASE_DIR / "roles.json"
PROFILES_FILE = WORKER_PROFILES_FILE
HEALTH_FILE = WORKER_HEALTH_FILE

REQUIRED_ROLES = {
    "coder",
    "debugger",
    "tester",
    "architect",
    "reviewer",
}
STANDBY_ROLE = "standby"


class WorkerRouterError(Exception):
    """Base worker router exception."""


class NoWorkerAvailable(WorkerRouterError):
    """Raised when no eligible worker exists."""


class LeaseError(WorkerRouterError):
    """Raised for invalid lease operations."""


class ConfigurationError(WorkerRouterError):
    """Raised for invalid worker configuration."""


@dataclass(frozen=True)
class WorkerLease:
    worker_id: str
    role: str
    task_id: str
    leased_at: float
    standby: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}"
    )
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise ConfigurationError(f"Required JSON file is missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot read JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise ConfigurationError(f"JSON root must be an object: {path}")
    return payload


def load_registry_from_path(path: Path) -> Dict[str, Any]:
    if path == REGISTRY_FILE:
        try:
            return validate_registry()
        except RegistryError as exc:
            raise ConfigurationError(f"Invalid worker registry: {exc}") from exc

    payload = read_json(path)
    architecture = payload.get("architecture")
    if not isinstance(architecture, dict):
        raise ConfigurationError("Registry is missing architecture")
    workers = architecture.get("workers")
    if not isinstance(workers, dict):
        raise ConfigurationError("Registry is missing workers configuration")
    return payload


class WorkerRouter:
    """Registry-driven worker router with separate external/runtime failure state."""

    def __init__(
        self,
        health_file: Path = WORKER_HEALTH_FILE,
        state_file: Path = STATE_FILE,
        registry_file: Path = REGISTRY_FILE,
        profiles_file: Optional[Path] = None,
        roles_file: Optional[Path] = None,
    ) -> None:
        del profiles_file, roles_file

        self.health_file = health_file
        self.state_file = state_file
        self.registry_file = registry_file
        self._lock = threading.RLock()

        self.provider = ""
        self.model = ""
        self.worker_pools: Dict[str, List[str]] = {}

        self.external_healthy_connections: Set[str] = set()
        self.external_failed_connections: Set[str] = set()
        self.runtime_failed_connections: Set[str] = set()

        self.leases: Dict[str, WorkerLease] = {}
        self.active_standby_for: Optional[str] = None
        self.active_standby_worker: Optional[str] = None

        self._load_configuration()
        self._load_state()
        self._normalize_state()
        self._save_state()

    @property
    def healthy_connections(self) -> Set[str]:
        return set(self.external_healthy_connections) - set(
            self.runtime_failed_connections
        )

    @property
    def failed_connections(self) -> Set[str]:
        return set(self.external_failed_connections) | set(
            self.runtime_failed_connections
        )

    def _load_configuration(self) -> None:
        registry = load_registry_from_path(self.registry_file)
        workers = registry["architecture"].get("workers")
        if not isinstance(workers, dict):
            raise ConfigurationError("Registry workers configuration is invalid")

        provider = workers.get("provider")
        model = workers.get("model")
        roles = workers.get("roles")

        if not isinstance(provider, str) or not provider.strip():
            raise ConfigurationError("Worker provider must be a non-empty string")
        if not isinstance(model, str) or not model.strip():
            raise ConfigurationError("Worker model must be a non-empty string")
        if not isinstance(roles, dict) or not roles:
            raise ConfigurationError("Worker roles must be a non-empty object")

        pools: Dict[str, List[str]] = {}
        assigned: Set[str] = set()
        for role, values in roles.items():
            if not isinstance(role, str) or not role.strip():
                raise ConfigurationError("Worker role names must be non-empty")
            if not isinstance(values, list):
                raise ConfigurationError(f"Worker role pool must be a list: {role}")

            pool: List[str] = []
            for worker_id in values:
                if not isinstance(worker_id, str) or not worker_id.strip():
                    raise ConfigurationError(f"Invalid worker id in role: {role}")
                if worker_id in pool:
                    raise ConfigurationError(
                        f"Duplicate worker id in role {role}: {worker_id}"
                    )
                if worker_id in assigned:
                    raise ConfigurationError(
                        f"Worker assigned to multiple roles: {worker_id}"
                    )
                pool.append(worker_id)
                assigned.add(worker_id)
            pools[role] = pool

        for role in REQUIRED_ROLES:
            if not pools.get(role):
                raise ConfigurationError(
                    f"Required worker role has no configured pool: {role}"
                )
        if not pools.get(STANDBY_ROLE):
            raise ConfigurationError("No standby worker pool is configured")

        self.provider = provider
        self.model = model
        self.worker_pools = pools
        self._load_health(read_json(self.health_file))

    def _load_health(self, health: Dict[str, Any]) -> None:
        healthy: Set[str] = set()
        failed: Set[str] = set()
        good = {"HEALTHY", "READY", "VALID", "OK", "AVAILABLE"}

        results = health.get("results")
        if isinstance(results, dict):
            for worker_id, item in results.items():
                if not isinstance(worker_id, str):
                    continue
                if isinstance(item, dict):
                    status = str(item.get("status", "")).upper()
                elif isinstance(item, str):
                    status = item.upper()
                else:
                    continue
                (healthy if status in good else failed).add(worker_id)

        healthy_list = health.get("healthy")
        if isinstance(healthy_list, list):
            healthy.update(item for item in healthy_list if isinstance(item, str))

        failed_list = health.get("failed")
        if isinstance(failed_list, list):
            failed.update(item for item in failed_list if isinstance(item, str))

        workers = health.get("workers")
        if isinstance(workers, list):
            for item in workers:
                if not isinstance(item, dict):
                    continue
                worker_id = item.get("id")
                if not isinstance(worker_id, str):
                    continue
                status = str(item.get("status", "")).upper()
                if status in good:
                    healthy.add(worker_id)
                    failed.discard(worker_id)
                else:
                    failed.add(worker_id)
                    healthy.discard(worker_id)

        healthy.difference_update(failed)
        self.external_healthy_connections = healthy
        self.external_failed_connections = failed

    def refresh_health(self) -> None:
        with self._lock:
            self._load_health(read_json(self.health_file))
            self._save_state()

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.leases = {}
            self.active_standby_for = None
            self.active_standby_worker = None
            self.runtime_failed_connections = set()
            return

        runtime_failed = payload.get("runtime_failed_connections")
        if isinstance(runtime_failed, list):
            self.runtime_failed_connections = {
                worker_id for worker_id in runtime_failed if isinstance(worker_id, str)
            }
        else:
            legacy_runtime = payload.get("runtime_failed_workers")
            if isinstance(legacy_runtime, list):
                self.runtime_failed_connections = {
                    worker_id
                    for worker_id in legacy_runtime
                    if isinstance(worker_id, str)
                }

        leases = payload.get("leases")
        if isinstance(leases, dict):
            for task_id, data in leases.items():
                if not isinstance(task_id, str) or not isinstance(data, dict):
                    continue
                try:
                    lease = WorkerLease(
                        worker_id=str(data["worker_id"]),
                        role=str(data["role"]),
                        task_id=str(data["task_id"]),
                        leased_at=float(data["leased_at"]),
                        standby=bool(data.get("standby", False)),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if lease.task_id == task_id:
                    self.leases[task_id] = lease

        active_for = payload.get("active_standby_for")
        if isinstance(active_for, str):
            self.active_standby_for = active_for
        active_worker = payload.get("active_standby_worker")
        if isinstance(active_worker, str):
            self.active_standby_worker = active_worker

    def _normalize_state(self) -> None:
        all_configured = {
            worker_id for pool in self.worker_pools.values() for worker_id in pool
        }
        self.runtime_failed_connections &= all_configured

        valid: Dict[str, WorkerLease] = {}
        used_workers: Set[str] = set()
        for task_id, lease in self.leases.items():
            if lease.worker_id not in all_configured:
                continue
            if lease.worker_id in used_workers:
                continue
            if task_id != lease.task_id:
                continue
            valid[task_id] = lease
            used_workers.add(lease.worker_id)
        self.leases = valid

        if self.active_standby_worker:
            matching = next(
                (
                    lease
                    for lease in self.leases.values()
                    if lease.worker_id == self.active_standby_worker
                    and lease.standby
                ),
                None,
            )
            if matching is None:
                self.active_standby_worker = None
                self.active_standby_for = None

    def _save_state(self) -> None:
        atomic_write_json(
            self.state_file,
            {
                "version": 4,
                "updated_at": time.time(),
                "registry_file": str(self.registry_file),
                "provider": self.provider,
                "model": self.model,
                "external_healthy_connections": sorted(self.external_healthy_connections),
                "external_failed_connections": sorted(self.external_failed_connections),
                "runtime_failed_connections": sorted(self.runtime_failed_connections),
                "healthy_connections": sorted(self.healthy_connections),
                "failed_connections": sorted(self.failed_connections),
                "leases": {
                    task_id: lease.to_dict() for task_id, lease in self.leases.items()
                },
                "active_standby_for": self.active_standby_for,
                "active_standby_worker": self.active_standby_worker,
            },
        )

    def _worker_is_leased(self, worker_id: str) -> bool:
        return any(lease.worker_id == worker_id for lease in self.leases.values())

    def _healthy_for_role(self, role: str) -> List[str]:
        return [
            worker_id
            for worker_id in self.worker_pools.get(role, [])
            if worker_id in self.external_healthy_connections
            and worker_id not in self.external_failed_connections
            and worker_id not in self.runtime_failed_connections
            and not self._worker_is_leased(worker_id)
        ]

    def acquire(self, role: str, task_id: str) -> WorkerLease:
        if role not in REQUIRED_ROLES:
            raise ConfigurationError(f"Unknown required role: {role}")
        if not isinstance(task_id, str) or not task_id.strip():
            raise LeaseError("task_id must be a non-empty string")

        with self._lock:
            self._load_health(read_json(self.health_file))
            if task_id in self.leases:
                raise LeaseError(f"Task already has a worker lease: {task_id}")

            candidates = self._healthy_for_role(role)
            if candidates:
                lease = WorkerLease(
                    worker_id=candidates[0],
                    role=role,
                    task_id=task_id,
                    leased_at=time.time(),
                    standby=False,
                )
                self.leases[task_id] = lease
                self._save_state()
                return lease

            if self.active_standby_worker is None and self.active_standby_for is None:
                standby_candidates = self._healthy_for_role(STANDBY_ROLE)
                if standby_candidates:
                    lease = WorkerLease(
                        worker_id=standby_candidates[0],
                        role=role,
                        task_id=task_id,
                        leased_at=time.time(),
                        standby=True,
                    )
                    self.leases[task_id] = lease
                    self.active_standby_for = role
                    self.active_standby_worker = lease.worker_id
                    self._save_state()
                    return lease

            raise NoWorkerAvailable(f"No healthy worker available for role: {role}")

    def release(self, task_id: str) -> WorkerLease:
        with self._lock:
            lease = self.leases.pop(task_id, None)
            if lease is None:
                raise LeaseError(f"No active lease found for task: {task_id}")
            if lease.standby:
                if self.active_standby_worker == lease.worker_id:
                    self.active_standby_worker = None
                if self.active_standby_for == lease.role:
                    self.active_standby_for = None
            self._save_state()
            return lease

    def mark_failed(self, worker_id: str) -> None:
        with self._lock:
            configured = {
                item for pool in self.worker_pools.values() for item in pool
            }
            if worker_id not in configured:
                raise ConfigurationError(f"Unknown worker connection: {worker_id}")
            self.runtime_failed_connections.add(worker_id)
            self.external_healthy_connections.discard(worker_id)
            self._save_state()

    def mark_healthy(self, worker_id: str) -> None:
        with self._lock:
            configured = {
                item for pool in self.worker_pools.values() for item in pool
            }
            if worker_id not in configured:
                raise ConfigurationError(f"Unknown worker connection: {worker_id}")
            self.runtime_failed_connections.discard(worker_id)
            self.external_failed_connections.discard(worker_id)
            self.external_healthy_connections.add(worker_id)
            self._save_state()

    def fail_current_worker(self, task_id: str) -> WorkerLease:
        with self._lock:
            lease = self.leases.get(task_id)
            if lease is None:
                raise LeaseError(f"No active lease for task: {task_id}")
            self.runtime_failed_connections.add(lease.worker_id)
            self.leases.pop(task_id, None)
            if lease.standby:
                if self.active_standby_worker == lease.worker_id:
                    self.active_standby_worker = None
                if self.active_standby_for == lease.role:
                    self.active_standby_for = None
            self._save_state()
            return lease

    def active_leases(self) -> Dict[str, WorkerLease]:
        with self._lock:
            return dict(self.leases)

    def available_workers(self, role: str) -> List[str]:
        with self._lock:
            self._load_health(read_json(self.health_file))
            return list(self._healthy_for_role(role))

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self._load_health(read_json(self.health_file))
            return {
                "version": 4,
                "registry_file": str(self.registry_file),
                "provider": self.provider,
                "model": self.model,
                "pools": {
                    role: list(pool) for role, pool in self.worker_pools.items()
                },
                "external_healthy": sorted(self.external_healthy_connections),
                "external_failed": sorted(self.external_failed_connections),
                "runtime_failed": sorted(self.runtime_failed_connections),
                "healthy": sorted(self.healthy_connections),
                "failed": sorted(self.failed_connections),
                "leases": {
                    task_id: lease.to_dict() for task_id, lease in self.leases.items()
                },
                "active_standby_for": self.active_standby_for,
                "active_standby_worker": self.active_standby_worker,
            }

    def reset_runtime_state(self) -> None:
        with self._lock:
            self.leases = {}
            self.active_standby_for = None
            self.active_standby_worker = None
            self.runtime_failed_connections = set()
            self._save_state()


def build_synthetic_health(router: WorkerRouter) -> Dict[str, Any]:
    all_workers = sorted(
        {
            worker_id
            for pool in router.worker_pools.values()
            for worker_id in pool
        }
    )
    return {"healthy": all_workers, "failed": []}


def synthetic_test() -> int:
    print("=" * 70)
    print("WORKER ROUTER REGISTRY SYNTHETIC TEST")
    print("=" * 70)

    state_file = BASE_DIR / "worker_router_test_state.json"
    health_file = BASE_DIR / "worker_router_test_health.json"
    for path in (state_file, health_file):
        if path.exists():
            path.unlink()

    registry = validate_registry()
    workers_cfg = registry["architecture"]["workers"]
    all_workers = [
        worker_id
        for pool in workers_cfg["roles"].values()
        for worker_id in pool
    ]
    health_file.write_text(
        json.dumps({"healthy": sorted(all_workers), "failed": []}, indent=2),
        encoding="utf-8",
    )

    router = WorkerRouter(health_file=health_file, state_file=state_file)

    for role in REQUIRED_ROLES:
        if not router.worker_pools.get(role):
            raise AssertionError(f"Missing configured role pool: {role}")
    print(f"TEST 1 registry-driven role pools ({len(router.worker_pools)} roles): PASS ✅")

    leases = []
    for role in REQUIRED_ROLES:
        lease = router.acquire(role, f"TASK-{role}")
        leases.append(lease)
        if lease.standby:
            raise AssertionError(f"Unexpected standby lease for {role}")

    workers = [lease.worker_id for lease in leases]
    if len(workers) != len(set(workers)):
        raise AssertionError("A worker was leased more than once")
    print("TEST 2 normal acquisition + global uniqueness: PASS ✅")

    try:
        router.acquire("coder", "TASK-coder")
    except LeaseError:
        print("TEST 3 duplicate task acquisition rejection: PASS ✅")
    else:
        raise AssertionError("Duplicate task acquisition was accepted")

    for lease in leases:
        router.release(lease.task_id)

    first = router.acquire("coder", "TASK-CODER-FAIL-1")
    first_pool = router.worker_pools["coder"]
    expected_next = next((worker_id for worker_id in first_pool if worker_id != first.worker_id), None)
    router.fail_current_worker("TASK-CODER-FAIL-1")
    second = router.acquire("coder", "TASK-CODER-FAIL-2")
    if expected_next is not None and second.worker_id != expected_next:
        raise AssertionError("Failure rotation did not select next configured worker")
    print("TEST 4 failure rotation: PASS ✅")
    router.release("TASK-CODER-FAIL-2")

    coder_pool = list(router.worker_pools["coder"])
    for worker_id in coder_pool:
        router.mark_failed(worker_id)

    standby = router.acquire("coder", "TASK-CODER-STANDBY")
    if not standby.standby:
        raise AssertionError("Standby flag not set")
    if standby.worker_id not in router.worker_pools[STANDBY_ROLE]:
        raise AssertionError("Unconfigured worker was used as standby")
    print("TEST 5 standby promotion: PASS ✅")

    router.release("TASK-CODER-STANDBY")
    print("TEST 6 lease release: PASS ✅")

    router.reset_runtime_state()
    router.refresh_health()
    persisted = router.acquire("coder", "TASK-PERSIST-1")
    restored = WorkerRouter(health_file=health_file, state_file=state_file)
    restored_lease = restored.active_leases().get("TASK-PERSIST-1")
    if restored_lease is None or restored_lease.worker_id != persisted.worker_id:
        raise AssertionError("Lease persistence failed")
    print("TEST 7 state persistence: PASS ✅")
    restored.release("TASK-PERSIST-1")

    for path in (state_file, health_file):
        if path.exists():
            path.unlink()

    print("=" * 70)
    print("WORKER ROUTER REGISTRY TEST PASSED ✅")
    print("=" * 70)
    return 0


def main() -> int:
    try:
        return synthetic_test()
    except Exception as exc:
        print()
        print("=" * 70)
        print("WORKER ROUTER REGISTRY TEST FAILED ❌")
        print("=" * 70)
        print(f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
