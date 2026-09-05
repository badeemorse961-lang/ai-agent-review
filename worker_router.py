from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ============================================================================
# WORKER ROUTER v2
#
# Responsibilities:
#   - Select workers only from their configured role pool.
#   - Exclude unhealthy/failed connections.
#   - Prevent double leasing.
#   - Release leases safely.
#   - Promote standby only when a required role is exhausted.
#   - Persist router state atomically.
#   - Provide deterministic synthetic tests without API inference.
# ============================================================================


BASE_DIR = Path(__file__).resolve().parent

WORKER_PROFILES_FILE = BASE_DIR / "worker_profiles.json"
WORKER_HEALTH_FILE = BASE_DIR / "groq_worker_health.json"
ROLES_FILE = BASE_DIR / "roles.json"

STATE_FILE = BASE_DIR / "worker_router_state.json"


REQUIRED_ROLES = {
    "coder",
    "debugger",
    "tester",
    "architect",
    "reviewer",
}

STANDBY_ROLE = "standby"


# ============================================================================
# Exceptions
# ============================================================================


class WorkerRouterError(Exception):
    """Base worker router exception."""


class NoWorkerAvailable(WorkerRouterError):
    """Raised when no eligible worker exists."""


class LeaseError(WorkerRouterError):
    """Raised for invalid lease operations."""


class ConfigurationError(WorkerRouterError):
    """Raised for invalid worker configuration."""


# ============================================================================
# Data structures
# ============================================================================


@dataclass(frozen=True)
class WorkerLease:
    worker_id: str
    role: str
    task_id: str
    leased_at: float
    standby: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# Utility
# ============================================================================


def atomic_write_json(
    path: Path,
    payload: Dict[str, Any],
) -> None:
    """
    Atomic JSON persistence.

    The temporary file is created beside the target, flushed, fsynced,
    then atomically replaced.
    """

    temp = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}"
    )

    try:
        with temp.open(
            "w",
            encoding="utf-8",
        ) as handle:
            json.dump(
                payload,
                handle,
                indent=2,
                ensure_ascii=False,
            )
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
        raise ConfigurationError(
            f"Required configuration file is missing: {path.name}"
        )

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as handle:
            payload = json.load(handle)

    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(
            f"Cannot read configuration file: {path.name}"
        ) from exc

    if not isinstance(payload, dict):
        raise ConfigurationError(
            f"Configuration root must be an object: {path.name}"
        )

    return payload


# ============================================================================
# Worker Router
# ============================================================================


class WorkerRouter:
    def __init__(
        self,
        profiles_file: Path = WORKER_PROFILES_FILE,
        health_file: Path = WORKER_HEALTH_FILE,
        roles_file: Path = ROLES_FILE,
        state_file: Path = STATE_FILE,
    ):
        self.profiles_file = profiles_file
        self.health_file = health_file
        self.roles_file = roles_file
        self.state_file = state_file

        self._lock = threading.RLock()

        self.worker_pools: Dict[str, List[str]] = {}
        self.worker_model: Dict[str, str] = {}
        self.healthy_connections: Set[str] = set()
        self.failed_connections: Set[str] = set()

        self.leases: Dict[str, WorkerLease] = {}

        # Tracks whether the standby is currently helping a specific role.
        self.active_standby_for: Optional[str] = None
        self.active_standby_worker: Optional[str] = None

        self._load_configuration()
        self._load_state()
        self._normalize_state()
        self._save_state()

    # ----------------------------------------------------------------------
    # Configuration
    # ----------------------------------------------------------------------

    def _load_configuration(self) -> None:
        profiles = read_json(self.profiles_file)
        health = read_json(self.health_file)
        roles = read_json(self.roles_file)

        self._load_health(health)
        self._load_worker_profiles(profiles)
        self._load_role_pools(roles)

        if not self.worker_pools:
            raise ConfigurationError(
                "No worker role pools were discovered."
            )

        for role in REQUIRED_ROLES:
            if not self.worker_pools.get(role):
                raise ConfigurationError(
                    f"Required worker role has no configured pool: {role}"
                )

        if not self.worker_pools.get(STANDBY_ROLE):
            raise ConfigurationError(
                "No standby worker pool is configured."
            )

    # ----------------------------------------------------------------------
    # Health parsing
    # ----------------------------------------------------------------------

    def _load_health(
        self,
        health: Dict[str, Any],
    ) -> None:
        """
        Supports the current health JSON style while being tolerant of
        small schema variations.
        """

        healthy: Set[str] = set()
        failed: Set[str] = set()

        # Common form:
        # {
        #   "results": {
        #       "GROQ-01": {"status": "HEALTHY"},
        #       ...
        #   }
        # }

        results = health.get("results")

        if isinstance(results, dict):
            for worker_id, item in results.items():
                if not isinstance(worker_id, str):
                    continue

                if isinstance(item, dict):
                    status = str(
                        item.get("status", "")
                    ).upper()

                    if status in {
                        "HEALTHY",
                        "READY",
                        "VALID",
                        "OK",
                    }:
                        healthy.add(worker_id)
                    else:
                        failed.add(worker_id)

                elif isinstance(item, str):
                    status = item.upper()

                    if status in {
                        "HEALTHY",
                        "READY",
                        "VALID",
                        "OK",
                    }:
                        healthy.add(worker_id)
                    else:
                        failed.add(worker_id)

        # Alternate form:
        # {
        #   "healthy": ["GROQ-01", ...],
        #   "failed": ["GROQ-09", ...]
        # }

        healthy_list = health.get("healthy")

        if isinstance(healthy_list, list):
            healthy.update(
                str(item)
                for item in healthy_list
                if isinstance(item, str)
            )

        failed_list = health.get("failed")

        if isinstance(failed_list, list):
            failed.update(
                str(item)
                for item in failed_list
                if isinstance(item, str)
            )

        # Alternate form:
        # {
        #   "workers": [
        #       {"id": "GROQ-01", "status": "HEALTHY"}
        #   ]
        # }

        workers = health.get("workers")

        if isinstance(workers, list):
            for item in workers:
                if not isinstance(item, dict):
                    continue

                worker_id = item.get("id")

                if not isinstance(worker_id, str):
                    continue

                status = str(
                    item.get("status", "")
                ).upper()

                if status in {
                    "HEALTHY",
                    "READY",
                    "VALID",
                    "OK",
                }:
                    healthy.add(worker_id)
                    failed.discard(worker_id)
                else:
                    failed.add(worker_id)
                    healthy.discard(worker_id)

        self.healthy_connections = healthy
        self.failed_connections = failed

    # ----------------------------------------------------------------------
    # Worker profile parsing
    # ----------------------------------------------------------------------

    def _load_worker_profiles(
        self,
        profiles: Dict[str, Any],
    ) -> None:
        """
        Reads worker model information when available.

        Pool membership is primarily obtained from roles.json so that
        role assignment remains the authoritative configuration.
        """

        workers = profiles.get("workers")

        if isinstance(workers, dict):
            for worker_id, item in workers.items():
                if not isinstance(worker_id, str):
                    continue

                if isinstance(item, dict):
                    model = item.get("model")

                    if isinstance(model, str):
                        self.worker_model[worker_id] = model

        elif isinstance(workers, list):
            for item in workers:
                if not isinstance(item, dict):
                    continue

                worker_id = item.get("id")

                if not isinstance(worker_id, str):
                    continue

                model = item.get("model")

                if isinstance(model, str):
                    self.worker_model[worker_id] = model

        # Some versions can use role-based structures:
        # {
        #   "roles": {
        #       "coder": {
        #           "workers": [...]
        #       }
        #   }
        # }

        role_profiles = profiles.get("roles")

        if isinstance(role_profiles, dict):
            for role_data in role_profiles.values():
                if not isinstance(role_data, dict):
                    continue

                role_workers = role_data.get("workers")

                if not isinstance(role_workers, list):
                    continue

                model = role_data.get("model")

                if not isinstance(model, str):
                    continue

                for worker_id in role_workers:
                    if isinstance(worker_id, str):
                        self.worker_model.setdefault(
                            worker_id,
                            model,
                        )

    # ----------------------------------------------------------------------
    # Role pool parsing
    # ----------------------------------------------------------------------

    def _load_role_pools(
        self,
        roles: Dict[str, Any],
    ) -> None:

        # Expected current shape:
        # {
        #   "workers": {
        #       "coder": ["GROQ-01", ...]
        #   }
        # }

        candidates = []

        if isinstance(roles.get("workers"), dict):
            candidates.append(
                roles["workers"]
            )

        if isinstance(roles.get("roles"), dict):
            candidates.append(
                roles["roles"]
            )

        if isinstance(roles.get("worker_roles"), dict):
            candidates.append(
                roles["worker_roles"]
            )

        if not candidates:
            raise ConfigurationError(
                "Could not find worker role assignments in roles.json."
            )

        merged: Dict[str, List[str]] = {}

        for source in candidates:
            for role, value in source.items():
                if isinstance(value, list):
                    ids = [
                        item
                        for item in value
                        if isinstance(item, str)
                    ]

                elif isinstance(value, dict):
                    ids_value = value.get(
                        "connections"
                    )

                    if ids_value is None:
                        ids_value = value.get(
                            "workers"
                        )

                    if isinstance(ids_value, list):
                        ids = [
                            item
                            for item in ids_value
                            if isinstance(item, str)
                        ]
                    else:
                        ids = []

                else:
                    ids = []

                if ids:
                    merged.setdefault(
                        role,
                        [],
                    )

                    for worker_id in ids:
                        if worker_id not in merged[role]:
                            merged[role].append(worker_id)

        self.worker_pools = merged

    # ----------------------------------------------------------------------
    # State
    # ----------------------------------------------------------------------

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return

        try:
            payload = json.loads(
                self.state_file.read_text(
                    encoding="utf-8"
                )
            )
        except (OSError, json.JSONDecodeError):
            # Corrupt state must not silently become an active lease set.
            self.leases = {}
            self.active_standby_for = None
            self.active_standby_worker = None
            return

        leases_payload = payload.get("leases", {})

        if isinstance(leases_payload, dict):
            for task_id, data in leases_payload.items():
                if not isinstance(task_id, str):
                    continue

                if not isinstance(data, dict):
                    continue

                worker_id = data.get("worker_id")
                role = data.get("role")
                leased_at = data.get("leased_at")
                standby = data.get("standby", False)

                if not isinstance(worker_id, str):
                    continue

                if not isinstance(role, str):
                    continue

                if not isinstance(leased_at, (int, float)):
                    continue

                self.leases[task_id] = WorkerLease(
                    worker_id=worker_id,
                    role=role,
                    task_id=task_id,
                    leased_at=float(leased_at),
                    standby=bool(standby),
                )

        active = payload.get(
            "active_standby_for"
        )

        if isinstance(active, str):
            self.active_standby_for = active

        worker = payload.get(
            "active_standby_worker"
        )

        if isinstance(worker, str):
            self.active_standby_worker = worker

    def _normalize_state(self) -> None:
        """
        Remove impossible/stale lease records.

        A worker may only be leased once globally.
        """

        valid: Dict[str, WorkerLease] = {}
        used_workers: Set[str] = set()

        for task_id, lease in self.leases.items():
            if lease.worker_id in used_workers:
                continue

            if task_id != lease.task_id:
                continue

            valid[task_id] = lease
            used_workers.add(
                lease.worker_id
            )

        self.leases = valid

        if self.active_standby_worker:
            standby_lease = next(
                (
                    lease
                    for lease in self.leases.values()
                    if lease.worker_id
                    == self.active_standby_worker
                ),
                None,
            )

            if standby_lease is None:
                self.active_standby_worker = None
                self.active_standby_for = None

    def _save_state(self) -> None:
        with self._lock:
            payload = {
                "version": 2,
                "updated_at": time.time(),
                "healthy_connections": sorted(
                    self.healthy_connections
                ),
                "failed_connections": sorted(
                    self.failed_connections
                ),
                "leases": {
                    task_id: lease.to_dict()
                    for task_id, lease in self.leases.items()
                },
                "active_standby_for": (
                    self.active_standby_for
                ),
                "active_standby_worker": (
                    self.active_standby_worker
                ),
            }

            atomic_write_json(
                self.state_file,
                payload,
            )

    # ----------------------------------------------------------------------
    # Health control
    # ----------------------------------------------------------------------

    def mark_failed(
        self,
        worker_id: str,
    ) -> None:
        with self._lock:
            self.failed_connections.add(
                worker_id
            )
            self.healthy_connections.discard(
                worker_id
            )

            self._save_state()

    def mark_healthy(
        self,
        worker_id: str,
    ) -> None:
        with self._lock:
            self.healthy_connections.add(
                worker_id
            )
            self.failed_connections.discard(
                worker_id
            )

            self._save_state()

    # ----------------------------------------------------------------------
    # Role filtering
    # ----------------------------------------------------------------------

    def _healthy_for_role(
        self,
        role: str,
    ) -> List[str]:
        pool = self.worker_pools.get(
            role,
            [],
        )

        return [
            worker_id
            for worker_id in pool
            if worker_id in self.healthy_connections
            and worker_id not in self.failed_connections
            and not self._worker_is_leased(
                worker_id
            )
        ]

    def _worker_is_leased(
        self,
        worker_id: str,
    ) -> bool:
        """
        Correct global lease check.

        This explicitly compares against WorkerLease.worker_id values,
        not against unrelated task identifiers.
        """

        return any(
            lease.worker_id == worker_id
            for lease in self.leases.values()
        )

    def _task_exists(
        self,
        task_id: str,
    ) -> bool:
        return task_id in self.leases

    # ----------------------------------------------------------------------
    # Acquire
    # ----------------------------------------------------------------------

    def acquire(
        self,
        role: str,
        task_id: str,
    ) -> WorkerLease:
        if role not in REQUIRED_ROLES:
            raise ConfigurationError(
                f"Unknown required role: {role}"
            )

        if not isinstance(task_id, str) or not task_id.strip():
            raise LeaseError(
                "task_id must be a non-empty string."
            )

        with self._lock:
            # Correct task uniqueness check.
            if self._task_exists(task_id):
                raise LeaseError(
                    f"Task already has a worker lease: {task_id}"
                )

            # --------------------------------------------------------------
            # Normal role pool
            # --------------------------------------------------------------

            candidates = self._healthy_for_role(
                role
            )

            if candidates:
                worker_id = candidates[0]

                lease = WorkerLease(
                    worker_id=worker_id,
                    role=role,
                    task_id=task_id,
                    leased_at=time.time(),
                    standby=False,
                )

                self.leases[task_id] = lease
                self._save_state()

                return lease

            # --------------------------------------------------------------
            # Standby promotion
            # --------------------------------------------------------------

            if (
                self.active_standby_worker is None
                and self.active_standby_for is None
            ):
                standby_candidates = (
                    self._healthy_for_role(
                        STANDBY_ROLE
                    )
                )

                if standby_candidates:
                    worker_id = standby_candidates[0]

                    lease = WorkerLease(
                        worker_id=worker_id,
                        role=role,
                        task_id=task_id,
                        leased_at=time.time(),
                        standby=True,
                    )

                    self.leases[task_id] = lease
                    self.active_standby_for = role
                    self.active_standby_worker = worker_id

                    self._save_state()

                    return lease

            raise NoWorkerAvailable(
                f"No healthy worker available for role: {role}"
            )

    # ----------------------------------------------------------------------
    # Release
    # ----------------------------------------------------------------------

    def release(
        self,
        task_id: str,
    ) -> WorkerLease:
        with self._lock:
            lease = self.leases.pop(
                task_id,
                None,
            )

            if lease is None:
                raise LeaseError(
                    f"No active lease found for task: {task_id}"
                )

            if lease.standby:
                if (
                    self.active_standby_worker
                    == lease.worker_id
                ):
                    self.active_standby_worker = None

                if (
                    self.active_standby_for
                    == lease.role
                ):
                    self.active_standby_for = None

            self._save_state()

            return lease

    # ----------------------------------------------------------------------
    # Runtime failure
    # ----------------------------------------------------------------------

    def fail_current_worker(
        self,
        task_id: str,
    ) -> Optional[WorkerLease]:
        """
        Mark the currently leased worker as failed and release it.

        The next acquire() call will select the next healthy worker in the
        role's configured order.
        """

        with self._lock:
            lease = self.leases.get(
                task_id
            )

            if lease is None:
                raise LeaseError(
                    f"No active lease for task: {task_id}"
                )

            self.mark_failed(
                lease.worker_id
            )

            return self.release(
                task_id
            )

    # ----------------------------------------------------------------------
    # Inspection
    # ----------------------------------------------------------------------

    def active_leases(self) -> Dict[str, WorkerLease]:
        with self._lock:
            return dict(
                self.leases
            )

    def available_workers(
        self,
        role: str,
    ) -> List[str]:
        with self._lock:
            return list(
                self._healthy_for_role(
                    role
                )
            )

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": 2,
                "healthy": sorted(
                    self.healthy_connections
                ),
                "failed": sorted(
                    self.failed_connections
                ),
                "pools": {
                    role: list(pool)
                    for role, pool
                    in self.worker_pools.items()
                },
                "leases": {
                    task_id: lease.to_dict()
                    for task_id, lease
                    in self.leases.items()
                },
                "active_standby_for": (
                    self.active_standby_for
                ),
                "active_standby_worker": (
                    self.active_standby_worker
                ),
            }

    # ----------------------------------------------------------------------
    # Reset
    # ----------------------------------------------------------------------

    def reset_runtime_state(self) -> None:
        with self._lock:
            self.leases = {}
            self.active_standby_for = None
            self.active_standby_worker = None

            self._save_state()


# ============================================================================
# Synthetic Test Helpers
# ============================================================================


def build_router_for_test(
    state_file: Path,
) -> WorkerRouter:
    """
    Creates a deterministic in-memory-like router using temporary
    configuration files.

    No API calls are performed.
    """

    profiles_file = state_file.with_name(
        "worker_router_test_profiles.json"
    )

    health_file = state_file.with_name(
        "worker_router_test_health.json"
    )

    roles_file = state_file.with_name(
        "worker_router_test_roles.json"
    )

    profiles = {
        "workers": {
            "GROQ-01": {
                "model": "openai/gpt-oss-120b"
            },
            "GROQ-02": {
                "model": "openai/gpt-oss-120b"
            },
            "GROQ-03": {
                "model": "openai/gpt-oss-120b"
            },
            "GROQ-04": {
                "model": "openai/gpt-oss-120b"
            },
            "GROQ-05": {
                "model": "openai/gpt-oss-120b"
            },
            "GROQ-15": {
                "model": "openai/gpt-oss-120b"
            },
        }
    }

    health = {
        "healthy": [
            "GROQ-01",
            "GROQ-02",
            "GROQ-03",
            "GROQ-04",
            "GROQ-05",
            "GROQ-15",
        ],
        "failed": [],
    }

    roles = {
        "workers": {
            "coder": [
                "GROQ-01",
                "GROQ-02",
                "GROQ-03",
                "GROQ-04",
            ],
            "debugger": [
                "GROQ-05",
            ],
            "tester": [
                "GROQ-02",
            ],
            "architect": [
                "GROQ-03",
            ],
            "reviewer": [
                "GROQ-04",
            ],
            "standby": [
                "GROQ-15",
            ],
        }
    }

    profiles_file.write_text(
        json.dumps(
            profiles,
            indent=2,
        ),
        encoding="utf-8",
    )

    health_file.write_text(
        json.dumps(
            health,
            indent=2,
        ),
        encoding="utf-8",
    )

    roles_file.write_text(
        json.dumps(
            roles,
            indent=2,
        ),
        encoding="utf-8",
    )

    return WorkerRouter(
        profiles_file=profiles_file,
        health_file=health_file,
        roles_file=roles_file,
        state_file=state_file,
    )


# ============================================================================
# Synthetic Test
# ============================================================================


def synthetic_test() -> int:
    print("=" * 70)
    print("WORKER ROUTER SYNTHETIC TEST")
    print("=" * 70)
    print()

    test_state = BASE_DIR / "worker_router_test_state.json"

    for path in [
        test_state,
        test_state.with_name(
            "worker_router_test_profiles.json"
        ),
        test_state.with_name(
            "worker_router_test_health.json"
        ),
        test_state.with_name(
            "worker_router_test_roles.json"
        ),
    ]:
        if path.exists():
            path.unlink()

    router = build_router_for_test(
        test_state
    )

    # ----------------------------------------------------------------------
    # TEST 1: Normal role acquisition
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 1: NORMAL ROLE ACQUISITION")
    print("-" * 70)

    acquisitions = {
        "coder": router.acquire(
            "coder",
            "TASK-CODER-01",
        ),
        "debugger": router.acquire(
            "debugger",
            "TASK-DEBUG-01",
        ),
        "tester": router.acquire(
            "tester",
            "TASK-TEST-01",
        ),
        "architect": router.acquire(
            "architect",
            "TASK-ARCH-01",
        ),
        "reviewer": router.acquire(
            "reviewer",
            "TASK-REVIEW-01",
        ),
    }

    for role, lease in acquisitions.items():
        print(
            f"{role:<10} -> "
            f"{lease.worker_id} "
            f"(standby={lease.standby})"
        )

        if lease.role != role:
            raise AssertionError(
                f"Wrong role returned for {role}"
            )

        if lease.standby:
            raise AssertionError(
                f"Unexpected standby for {role}"
            )

    print("Normal role acquisition: PASS ✅")
    print()

    # ----------------------------------------------------------------------
    # TEST 2: Global lease uniqueness
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 2: GLOBAL LEASE UNIQUENESS")
    print("-" * 70)

    leased_workers = [
        lease.worker_id
        for lease in router.active_leases().values()
    ]

    if len(leased_workers) != len(
        set(leased_workers)
    ):
        raise AssertionError(
            "Same worker was leased more than once."
        )

    print(
        "Leased worker count :",
        len(leased_workers),
    )

    print(
        "Unique worker count :",
        len(set(leased_workers)),
    )

    print("Concurrent/global lease uniqueness: PASS ✅")
    print()

    # ----------------------------------------------------------------------
    # TEST 3: Same task cannot acquire twice
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 3: SAME TASK DOUBLE ACQUIRE -> REJECT")
    print("-" * 70)

    try:
        router.acquire(
            "coder",
            "TASK-CODER-01",
        )

    except LeaseError:
        print(
            "Duplicate task acquisition rejected: PASS ✅"
        )

    else:
        raise AssertionError(
            "Same task acquired a second worker."
        )

    print()

    # ----------------------------------------------------------------------
    # TEST 4: Release
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 4: RELEASE")
    print("-" * 70)

    released = router.release(
        "TASK-CODER-01"
    )

    print(
        f"Released : {released.worker_id}"
    )

    if "TASK-CODER-01" in router.active_leases():
        raise AssertionError(
            "Lease remained active after release."
        )

    if (
        released.worker_id
        in [
            lease.worker_id
            for lease in router.active_leases().values()
        ]
    ):
        raise AssertionError(
            "Released worker still appears leased."
        )

    print("Release: PASS ✅")
    print()

    # ----------------------------------------------------------------------
    # Release remaining normal tasks.
    # ----------------------------------------------------------------------

    for task_id in [
        "TASK-DEBUG-01",
        "TASK-TEST-01",
        "TASK-ARCH-01",
        "TASK-REVIEW-01",
    ]:
        router.release(task_id)

    # ----------------------------------------------------------------------
    # TEST 5: Failed worker -> next worker
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 5: WORKER FAILURE -> NEXT WORKER")
    print("-" * 70)

    first = router.acquire(
        "coder",
        "TASK-CODER-FAIL-01",
    )

    print(
        "First worker  :",
        first.worker_id,
    )

    if first.worker_id != "GROQ-01":
        raise AssertionError(
            "Unexpected initial coder worker."
        )

    router.fail_current_worker(
        "TASK-CODER-FAIL-01"
    )

    second = router.acquire(
        "coder",
        "TASK-CODER-FAIL-02",
    )

    print(
        "Next worker    :",
        second.worker_id,
    )

    if second.worker_id != "GROQ-02":
        raise AssertionError(
            "Router did not advance to next healthy coder."
        )

    print(
        "Failure rotation: NEXT_WORKER_AVAILABLE ✅"
    )
    print()

    router.release(
        "TASK-CODER-FAIL-02"
    )

    # ----------------------------------------------------------------------
    # TEST 6: Standby promotion
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 6: STANDBY PROMOTION")
    print("-" * 70)

    # Fail all coder workers.
    for worker_id in [
        "GROQ-02",
        "GROQ-03",
        "GROQ-04",
    ]:
        router.mark_failed(
            worker_id
        )

    # GROQ-01 is already failed by TEST 5.
    standby_lease = router.acquire(
        "coder",
        "TASK-CODER-STANDBY",
    )

    print(
        "Standby worker :",
        standby_lease.worker_id,
    )

    print(
        "Standby flag   :",
        standby_lease.standby,
    )

    if standby_lease.worker_id != "GROQ-15":
        raise AssertionError(
            "Standby worker was not promoted."
        )

    if standby_lease.standby is not True:
        raise AssertionError(
            "Standby lease flag is incorrect."
        )

    if router.active_standby_for != "coder":
        raise AssertionError(
            "Active standby role was not recorded."
        )

    print("Standby promotion: PASS ✅")
    print()

    # ----------------------------------------------------------------------
    # TEST 7: Second standby request must stop
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 7: STANDBY EXHAUSTION -> SAFE STOP")
    print("-" * 70)

    try:
        router.acquire(
            "coder",
            "TASK-CODER-STANDBY-2",
        )

    except NoWorkerAvailable:
        print(
            "Second standby request rejected safely: PASS ✅"
        )

    else:
        raise AssertionError(
            "Router leased standby twice."
        )

    print()

    router.release(
        "TASK-CODER-STANDBY"
    )

    # ----------------------------------------------------------------------
    # TEST 8: Persistence
    # ----------------------------------------------------------------------

    print("-" * 70)
    print("TEST 8: STATE PERSISTENCE")
    print("-" * 70)

    router.reset_runtime_state()

    persisted_lease = router.acquire(
        "debugger",
        "TASK-PERSIST-01",
    )

    if not test_state.exists():
        raise AssertionError(
            "Router state file was not created."
        )

    restored = WorkerRouter(
        profiles_file=router.profiles_file,
        health_file=router.health_file,
        roles_file=router.roles_file,
        state_file=test_state,
    )

    restored_lease = (
        restored.active_leases()
        .get("TASK-PERSIST-01")
    )

    if restored_lease is None:
        raise AssertionError(
            "Persisted lease was not restored."
        )

    if (
        restored_lease.worker_id
        != persisted_lease.worker_id
    ):
        raise AssertionError(
            "Persisted lease worker differs."
        )

    print(
        "Persisted worker:",
        restored_lease.worker_id,
    )

    print("State persistence: PASS ✅")
    print()

    restored.release(
        "TASK-PERSIST-01"
    )

    # ----------------------------------------------------------------------
    # Cleanup synthetic configuration
    # ----------------------------------------------------------------------

    synthetic_files = [
        test_state,
        test_state.with_name(
            "worker_router_test_profiles.json"
        ),
        test_state.with_name(
            "worker_router_test_health.json"
        ),
        test_state.with_name(
            "worker_router_test_roles.json"
        ),
    ]

    for path in synthetic_files:
        if path.exists():
            path.unlink()

    # ----------------------------------------------------------------------
    # Final state
    # ----------------------------------------------------------------------

    print("=" * 70)
    print("WORKER ROUTER TEST PASSED ✅")
    print("=" * 70)

    return 0


# ============================================================================
# Main
# ============================================================================


def main() -> int:
    try:
        return synthetic_test()

    except Exception as exc:
        print()
        print("=" * 70)
        print("WORKER ROUTER TEST FAILED ❌")
        print("=" * 70)
        print(
            f"{type(exc).__name__}: {exc}"
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )