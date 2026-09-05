from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


# ============================================================================
# LEADER ROUTER v3
#
# Static configuration
#        +
# External health
#        +
# Runtime failures
#        ↓
# Effective availability
#        ↓
# Ultra primary routing
#        ↓
# Super failover
#        ↓
# SAFE STOP
#
# No API inference is performed by this file.
# ============================================================================


BASE_DIR = Path(__file__).resolve().parent

LEADER_PROFILES_FILE = BASE_DIR / "leader_profiles.json"
LEADER_HEALTH_FILE = BASE_DIR / "leader_health.json"
ROUTER_STATE_FILE = BASE_DIR / "leader_router_state.json"

PRIMARY_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
FAILOVER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

PRIMARY_TIER = "ULTRA"
FAILOVER_TIER = "SUPER"


# ============================================================================
# Exceptions
# ============================================================================


class LeaderRouterError(Exception):
    """Base leader router error."""


class LeaderConfigurationError(LeaderRouterError):
    """Invalid leader configuration."""


class LeaderUnavailable(LeaderRouterError):
    """No healthy leader account is available."""


class LeaderLeaseError(LeaderRouterError):
    """Invalid leader lease operation."""


# ============================================================================
# Data structures
# ============================================================================


@dataclass(frozen=True)
class LeaderLease:
    provider: str
    account_id: str
    model: str
    tier: str
    task_id: str
    leased_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# JSON helpers
# ============================================================================


def atomic_write_json(
    path: Path,
    payload: Dict[str, Any],
) -> None:
    temp_path = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}"
    )

    try:
        with temp_path.open(
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

        os.replace(
            temp_path,
            path,
        )

    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise LeaderConfigurationError(
            f"Missing configuration file: {path.name}"
        )

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LeaderConfigurationError(
            f"Cannot read JSON configuration: {path.name}"
        ) from exc

    if not isinstance(payload, dict):
        raise LeaderConfigurationError(
            f"Configuration root must be an object: {path.name}"
        )

    return payload


# ============================================================================
# Leader Router
# ============================================================================


class LeaderRouter:
    """
    Model-aware leader routing with two independent health layers:

    1. External health:
       Comes from leader_health.json.

    2. Runtime health:
       Failures observed during the current runtime.

    Effective account availability requires:

        configured
        AND externally healthy
        AND not externally failed
        AND not runtime failed
        AND not currently leased
    """

    def __init__(
        self,
        profiles_file: Path = LEADER_PROFILES_FILE,
        health_file: Path = LEADER_HEALTH_FILE,
        state_file: Path = ROUTER_STATE_FILE,
    ):
        self.profiles_file = profiles_file
        self.health_file = health_file
        self.state_file = state_file

        self._lock = threading.RLock()

        self.provider = "openrouter"

        self.primary_model = PRIMARY_MODEL
        self.failover_model = FAILOVER_MODEL

        self.primary_pool: List[str] = []
        self.failover_pool: List[str] = []

        # Provider/external health.
        self.external_healthy_by_model: Dict[
            str, Set[str]
        ] = {}

        self.external_failed_by_model: Dict[
            str, Set[str]
        ] = {}

        # Failures discovered during current runtime.
        self.runtime_failed_by_model: Dict[
            str, Set[str]
        ] = {}

        # Active task leases.
        self.leases: Dict[str, LeaderLease] = {}

        # Failure history.
        self.failure_history: List[Dict[str, Any]] = []

        self.active_tier: Optional[str] = None
        self.active_account: Optional[str] = None

        self._load_profiles()
        self._load_state()
        self.refresh_health()
        self._normalize_state()
        self._save_state()

    # ----------------------------------------------------------------------
    # Profile loading
    # ----------------------------------------------------------------------

    def _load_profiles(self) -> None:
        profiles = read_json(
            self.profiles_file
        )

        provider = profiles.get(
            "provider"
        )

        if isinstance(provider, str):
            self.provider = provider

        primary = profiles.get(
            "primary"
        )

        failover = profiles.get(
            "failover"
        )

        if isinstance(primary, dict):
            model = primary.get("model")

            if isinstance(model, str):
                self.primary_model = model

            pool = (
                primary.get("pool")
                or primary.get("accounts")
                or primary.get("connections")
            )

            if isinstance(pool, list):
                self.primary_pool = [
                    item
                    for item in pool
                    if isinstance(item, str)
                ]

        if isinstance(failover, dict):
            model = failover.get("model")

            if isinstance(model, str):
                self.failover_model = model

            pool = (
                failover.get("pool")
                or failover.get("accounts")
                or failover.get("connections")
            )

            if isinstance(pool, list):
                self.failover_pool = [
                    item
                    for item in pool
                    if isinstance(item, str)
                ]

        # Flattened schema compatibility.
        primary_model = profiles.get(
            "primary_model"
        )

        if isinstance(primary_model, str):
            self.primary_model = primary_model

        failover_model = profiles.get(
            "failover_model"
        )

        if isinstance(failover_model, str):
            self.failover_model = failover_model

        primary_pool = profiles.get(
            "primary_pool"
        )

        if isinstance(primary_pool, list):
            self.primary_pool = [
                item
                for item in primary_pool
                if isinstance(item, str)
            ]

        failover_pool = profiles.get(
            "failover_pool"
        )

        if isinstance(failover_pool, list):
            self.failover_pool = [
                item
                for item in failover_pool
                if isinstance(item, str)
            ]

        self.primary_pool = list(
            dict.fromkeys(
                self.primary_pool
            )
        )

        self.failover_pool = list(
            dict.fromkeys(
                self.failover_pool
            )
        )

        if not self.primary_pool:
            raise LeaderConfigurationError(
                "Primary leader pool is empty."
            )

        if not self.failover_pool:
            raise LeaderConfigurationError(
                "Failover leader pool is empty."
            )

    # ----------------------------------------------------------------------
    # External health
    # ----------------------------------------------------------------------

    def refresh_health(self) -> None:
        """
        Refresh external health only.

        Runtime failure information is intentionally preserved.
        """

        health = read_json(
            self.health_file
        )

        healthy_by_model: Dict[
            str, Set[str]
        ] = {}

        failed_by_model: Dict[
            str, Set[str]
        ] = {}

        # --------------------------------------------------------------
        # Schema A
        # --------------------------------------------------------------

        mappings = [
            ("Ultra", self.primary_model),
            ("ultra", self.primary_model),
            ("Super", self.failover_model),
            ("super", self.failover_model),
        ]

        for key, model in mappings:
            section = health.get(
                key
            )

            if not isinstance(section, dict):
                continue

            healthy = section.get(
                "healthy"
            )

            failed = section.get(
                "failed"
            )

            if isinstance(healthy, list):
                healthy_by_model.setdefault(
                    model,
                    set(),
                ).update(
                    item
                    for item in healthy
                    if isinstance(item, str)
                )

            if isinstance(failed, list):
                failed_by_model.setdefault(
                    model,
                    set(),
                ).update(
                    item
                    for item in failed
                    if isinstance(item, str)
                )

        # --------------------------------------------------------------
        # Schema B
        # --------------------------------------------------------------

        models = health.get(
            "models"
        )

        if isinstance(models, dict):
            for model, section in models.items():
                if not isinstance(model, str):
                    continue

                if not isinstance(section, dict):
                    continue

                healthy = section.get(
                    "healthy"
                )

                failed = section.get(
                    "failed"
                )

                if isinstance(healthy, list):
                    healthy_by_model.setdefault(
                        model,
                        set(),
                    ).update(
                        item
                        for item in healthy
                        if isinstance(item, str)
                    )

                if isinstance(failed, list):
                    failed_by_model.setdefault(
                        model,
                        set(),
                    ).update(
                        item
                        for item in failed
                        if isinstance(item, str)
                    )

        # --------------------------------------------------------------
        # Schema C
        # --------------------------------------------------------------

        results = health.get(
            "results"
        )

        if isinstance(results, dict):
            for account_id, result in results.items():
                if not isinstance(account_id, str):
                    continue

                if not isinstance(result, dict):
                    continue

                for key, model in [
                    ("ultra", self.primary_model),
                    ("Ultra", self.primary_model),
                    ("super", self.failover_model),
                    ("Super", self.failover_model),
                ]:
                    status = result.get(
                        key
                    )

                    if not isinstance(status, str):
                        continue

                    normalized = status.upper()

                    if normalized in {
                        "HEALTHY",
                        "READY",
                        "VALID",
                        "OK",
                        "AVAILABLE",
                    }:
                        healthy_by_model.setdefault(
                            model,
                            set(),
                        ).add(account_id)
                    else:
                        failed_by_model.setdefault(
                            model,
                            set(),
                        ).add(account_id)

        # --------------------------------------------------------------
        # Schema D
        # --------------------------------------------------------------

        accounts = health.get(
            "accounts"
        )

        if isinstance(accounts, list):
            for account in accounts:
                if not isinstance(account, dict):
                    continue

                account_id = (
                    account.get("id")
                    or account.get("account_id")
                )

                if not isinstance(account_id, str):
                    continue

                for key, model in [
                    ("ultra", self.primary_model),
                    ("Ultra", self.primary_model),
                    ("super", self.failover_model),
                    ("Super", self.failover_model),
                ]:
                    section = account.get(
                        key
                    )

                    if isinstance(section, dict):
                        status = section.get(
                            "status"
                        )
                    else:
                        status = section

                    if not isinstance(status, str):
                        continue

                    normalized = status.upper()

                    if normalized in {
                        "HEALTHY",
                        "READY",
                        "VALID",
                        "OK",
                        "AVAILABLE",
                    }:
                        healthy_by_model.setdefault(
                            model,
                            set(),
                        ).add(account_id)
                    else:
                        failed_by_model.setdefault(
                            model,
                            set(),
                        ).add(account_id)

        # Failed always wins.
        for model, failed in failed_by_model.items():
            healthy_by_model.setdefault(
                model,
                set(),
            ).difference_update(
                failed
            )

        self.external_healthy_by_model = (
            healthy_by_model
        )

        self.external_failed_by_model = (
            failed_by_model
        )

    # ----------------------------------------------------------------------
    # Runtime state
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
            return

        runtime_failed = payload.get(
            "runtime_failed_by_model"
        )

        if isinstance(runtime_failed, dict):
            for model, accounts in runtime_failed.items():
                if not isinstance(model, str):
                    continue

                if not isinstance(accounts, list):
                    continue

                self.runtime_failed_by_model[
                    model
                ] = {
                    account
                    for account in accounts
                    if isinstance(account, str)
                }

        leases = payload.get(
            "leases"
        )

        if isinstance(leases, dict):
            for task_id, item in leases.items():
                if not isinstance(task_id, str):
                    continue

                if not isinstance(item, dict):
                    continue

                try:
                    lease = LeaderLease(
                        provider=str(
                            item["provider"]
                        ),
                        account_id=str(
                            item["account_id"]
                        ),
                        model=str(
                            item["model"]
                        ),
                        tier=str(
                            item["tier"]
                        ),
                        task_id=str(
                            item["task_id"]
                        ),
                        leased_at=float(
                            item["leased_at"]
                        ),
                    )
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    continue

                if lease.task_id != task_id:
                    continue

                self.leases[
                    task_id
                ] = lease

        history = payload.get(
            "failure_history"
        )

        if isinstance(history, list):
            self.failure_history = [
                item
                for item in history
                if isinstance(item, dict)
            ]

        active_tier = payload.get(
            "active_tier"
        )

        if isinstance(active_tier, str):
            self.active_tier = active_tier

        active_account = payload.get(
            "active_account"
        )

        if isinstance(active_account, str):
            self.active_account = active_account

    def _normalize_state(self) -> None:
        valid: Dict[str, LeaderLease] = {}
        used_accounts: Set[str] = set()

        for task_id, lease in self.leases.items():
            if lease.account_id in used_accounts:
                continue

            valid[
                task_id
            ] = lease

            used_accounts.add(
                lease.account_id
            )

        self.leases = valid

    def _save_state(self) -> None:
        with self._lock:
            atomic_write_json(
                self.state_file,
                {
                    "version": 3,
                    "updated_at": time.time(),
                    "provider": self.provider,
                    "primary_model": self.primary_model,
                    "failover_model": self.failover_model,
                    "primary_pool": list(
                        self.primary_pool
                    ),
                    "failover_pool": list(
                        self.failover_pool
                    ),
                    "external_healthy_by_model": {
                        model: sorted(accounts)
                        for model, accounts
                        in self.external_healthy_by_model.items()
                    },
                    "external_failed_by_model": {
                        model: sorted(accounts)
                        for model, accounts
                        in self.external_failed_by_model.items()
                    },
                    "runtime_failed_by_model": {
                        model: sorted(accounts)
                        for model, accounts
                        in self.runtime_failed_by_model.items()
                    },
                    "active_tier": self.active_tier,
                    "active_account": self.active_account,
                    "leases": {
                        task_id: lease.to_dict()
                        for task_id, lease
                        in self.leases.items()
                    },
                    "failure_history": list(
                        self.failure_history
                    ),
                },
            )

    # ----------------------------------------------------------------------
    # Effective pools
    # ----------------------------------------------------------------------

    def _effective_pool(
        self,
        tier: str,
    ) -> List[str]:

        if tier == PRIMARY_TIER:
            model = self.primary_model
            configured = self.primary_pool

        elif tier == FAILOVER_TIER:
            model = self.failover_model
            configured = self.failover_pool

        else:
            raise LeaderConfigurationError(
                f"Unknown tier: {tier}"
            )

        external_healthy = (
            self.external_healthy_by_model.get(
                model,
                set(),
            )
        )

        external_failed = (
            self.external_failed_by_model.get(
                model,
                set(),
            )
        )

        runtime_failed = (
            self.runtime_failed_by_model.get(
                model,
                set(),
            )
        )

        leased_accounts = {
            lease.account_id
            for lease in self.leases.values()
        }

        return [
            account_id
            for account_id in configured
            if account_id in external_healthy
            and account_id not in external_failed
            and account_id not in runtime_failed
            and account_id not in leased_accounts
        ]

    def active_pool(
        self,
        tier: str,
    ) -> List[str]:

        with self._lock:
            self.refresh_health()

            return self._effective_pool(
                tier
            )

    # ----------------------------------------------------------------------
    # Acquire
    # ----------------------------------------------------------------------

    def acquire(
        self,
        task_id: str,
    ) -> LeaderLease:

        if not isinstance(
            task_id,
            str,
        ) or not task_id.strip():
            raise LeaderLeaseError(
                "task_id must be a non-empty string."
            )

        with self._lock:

            if task_id in self.leases:
                raise LeaderLeaseError(
                    f"Task already owns a leader lease: {task_id}"
                )

            self.refresh_health()

            # Primary first.
            primary_candidates = self._effective_pool(
                PRIMARY_TIER
            )

            if primary_candidates:
                account_id = primary_candidates[0]

                lease = LeaderLease(
                    provider=self.provider,
                    account_id=account_id,
                    model=self.primary_model,
                    tier=PRIMARY_TIER,
                    task_id=task_id,
                    leased_at=time.time(),
                )

                self.leases[
                    task_id
                ] = lease

                self.active_tier = PRIMARY_TIER
                self.active_account = account_id

                self._save_state()

                return lease

            # Failover second.
            failover_candidates = self._effective_pool(
                FAILOVER_TIER
            )

            if failover_candidates:
                account_id = failover_candidates[0]

                lease = LeaderLease(
                    provider=self.provider,
                    account_id=account_id,
                    model=self.failover_model,
                    tier=FAILOVER_TIER,
                    task_id=task_id,
                    leased_at=time.time(),
                )

                self.leases[
                    task_id
                ] = lease

                self.active_tier = FAILOVER_TIER
                self.active_account = account_id

                self._save_state()

                return lease

            self.active_tier = None
            self.active_account = None

            self._save_state()

            raise LeaderUnavailable(
                "No healthy Ultra or Super leader account is available."
            )

    # ----------------------------------------------------------------------
    # Release
    # ----------------------------------------------------------------------

    def release(
        self,
        task_id: str,
    ) -> LeaderLease:

        with self._lock:

            lease = self.leases.pop(
                task_id,
                None,
            )

            if lease is None:
                raise LeaderLeaseError(
                    f"No leader lease exists for task: {task_id}"
                )

            if not self.leases:
                self.active_tier = None
                self.active_account = None

            self._save_state()

            return lease

    # ----------------------------------------------------------------------
    # Runtime failure
    # ----------------------------------------------------------------------

    def fail_current_leader(
        self,
        task_id: str,
        reason: str = "runtime_failure",
    ) -> LeaderLease:

        with self._lock:

            lease = self.leases.get(
                task_id
            )

            if lease is None:
                raise LeaderLeaseError(
                    f"No active leader lease for task: {task_id}"
                )

            self.runtime_failed_by_model.setdefault(
                lease.model,
                set(),
            ).add(
                lease.account_id
            )

            self.failure_history.append(
                {
                    "timestamp": time.time(),
                    "task_id": task_id,
                    "account_id": lease.account_id,
                    "model": lease.model,
                    "tier": lease.tier,
                    "reason": reason,
                    "source": "runtime",
                }
            )

            self.leases.pop(
                task_id,
                None,
            )

            if not self.leases:
                self.active_tier = None
                self.active_account = None

            self._save_state()

            return lease

    # ----------------------------------------------------------------------
    # Mark healthy after explicit validation
    # ----------------------------------------------------------------------

    def mark_healthy(
        self,
        account_id: str,
        tier: str,
    ) -> None:

        with self._lock:

            if tier == PRIMARY_TIER:
                model = self.primary_model

            elif tier == FAILOVER_TIER:
                model = self.failover_model

            else:
                raise LeaderConfigurationError(
                    f"Unknown tier: {tier}"
                )

            self.runtime_failed_by_model.setdefault(
                model,
                set(),
            ).discard(
                account_id
            )

            self.external_failed_by_model.setdefault(
                model,
                set(),
            ).discard(
                account_id
            )

            self.external_healthy_by_model.setdefault(
                model,
                set(),
            ).add(
                account_id
            )

            self._save_state()

    # ----------------------------------------------------------------------
    # Clear runtime failures
    # ----------------------------------------------------------------------

    def clear_runtime_failures(self) -> None:
        with self._lock:
            self.runtime_failed_by_model = {}
            self._save_state()

    # ----------------------------------------------------------------------
    # Snapshot
    # ----------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:

        with self._lock:

            self.refresh_health()

            return {
                "version": 3,
                "provider": self.provider,

                "primary_model": self.primary_model,
                "failover_model": self.failover_model,

                "primary_configured": list(
                    self.primary_pool
                ),

                "primary_active": self._effective_pool(
                    PRIMARY_TIER
                ),

                "primary_external_failed": sorted(
                    self.external_failed_by_model.get(
                        self.primary_model,
                        set(),
                    )
                ),

                "primary_runtime_failed": sorted(
                    self.runtime_failed_by_model.get(
                        self.primary_model,
                        set(),
                    )
                ),

                "failover_configured": list(
                    self.failover_pool
                ),

                "failover_active": self._effective_pool(
                    FAILOVER_TIER
                ),

                "failover_external_failed": sorted(
                    self.external_failed_by_model.get(
                        self.failover_model,
                        set(),
                    )
                ),

                "failover_runtime_failed": sorted(
                    self.runtime_failed_by_model.get(
                        self.failover_model,
                        set(),
                    )
                ),

                "active_tier": self.active_tier,
                "active_account": self.active_account,

                "leases": {
                    task_id: lease.to_dict()
                    for task_id, lease
                    in self.leases.items()
                },

                "failure_history_count": len(
                    self.failure_history
                ),
            }

    # ----------------------------------------------------------------------
    # Runtime reset
    # ----------------------------------------------------------------------

    def reset_runtime(self) -> None:
        with self._lock:

            self.leases = {}
            self.failure_history = []
            self.runtime_failed_by_model = {}

            self.active_tier = None
            self.active_account = None

            self._save_state()


# ============================================================================
# Synthetic Configuration
# ============================================================================


def build_synthetic_router(
    state_file: Path,
) -> LeaderRouter:

    profiles_file = state_file.with_name(
        "leader_router_test_profiles.json"
    )

    health_file = state_file.with_name(
        "leader_router_test_health.json"
    )

    profiles = {
        "primary": {
            "provider": "openrouter",
            "model": PRIMARY_MODEL,
            "pool": [
                "OR-01",
                "OR-02",
                "OR-03",
                "OR-07",
                "OR-04",
            ],
        },

        "failover": {
            "provider": "openrouter",
            "model": FAILOVER_MODEL,
            "pool": [
                "OR-01",
                "OR-02",
                "OR-03",
            ],
        },
    }

    # OR-07 is externally unhealthy only for Ultra.
    health = {
        "models": {
            PRIMARY_MODEL: {
                "healthy": [
                    "OR-01",
                    "OR-02",
                    "OR-03",
                    "OR-04",
                ],
                "failed": [
                    "OR-07",
                ],
            },

            FAILOVER_MODEL: {
                "healthy": [
                    "OR-01",
                    "OR-02",
                    "OR-03",
                ],
                "failed": [],
            },
        }
    }

    profiles_file.write_text(
        json.dumps(
            profiles,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    health_file.write_text(
        json.dumps(
            health,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return LeaderRouter(
        profiles_file=profiles_file,
        health_file=health_file,
        state_file=state_file,
    )


# ============================================================================
# Synthetic Tests
# ============================================================================


def synthetic_test() -> int:

    print("=" * 70)
    print("LEADER ROUTER SYNTHETIC TEST")
    print("=" * 70)
    print()

    state_file = BASE_DIR / (
        "leader_router_test_state.json"
    )

    synthetic_files = [
        state_file,
        state_file.with_name(
            "leader_router_test_profiles.json"
        ),
        state_file.with_name(
            "leader_router_test_health.json"
        ),
    ]

    for path in synthetic_files:
        if path.exists():
            path.unlink()

    router = build_synthetic_router(
        state_file
    )

    # ======================================================================
    # TEST 1
    # ======================================================================

    print("-" * 70)
    print("TEST 1: HEALTH-AWARE PRIMARY POOL")
    print("-" * 70)

    ultra_pool = router.active_pool(
        PRIMARY_TIER
    )

    print(
        "Active Ultra pool:",
        ultra_pool,
    )

    if ultra_pool != [
        "OR-01",
        "OR-02",
        "OR-03",
        "OR-04",
    ]:
        raise AssertionError(
            f"Unexpected active Ultra pool: {ultra_pool}"
        )

    if "OR-07" in ultra_pool:
        raise AssertionError(
            "OR-07 was not excluded from Ultra."
        )

    print(
        "Model-specific health filtering: PASS ✅"
    )
    print()

    # ======================================================================
    # TEST 2
    # ======================================================================

    print("-" * 70)
    print("TEST 2: PRIMARY ULTRA ACQUISITION")
    print("-" * 70)

    lease_1 = router.acquire(
        "TASK-ULTRA-01"
    )

    print(
        "Account :",
        lease_1.account_id,
    )

    print(
        "Model   :",
        lease_1.model,
    )

    print(
        "Tier    :",
        lease_1.tier,
    )

    if lease_1.account_id != "OR-01":
        raise AssertionError(
            "Unexpected first Ultra account."
        )

    if lease_1.model != PRIMARY_MODEL:
        raise AssertionError(
            "Wrong primary model."
        )

    if lease_1.tier != PRIMARY_TIER:
        raise AssertionError(
            "Wrong primary tier."
        )

    print(
        "Primary acquisition: PASS ✅"
    )
    print()

    # ======================================================================
    # TEST 3
    # ======================================================================

    print("-" * 70)
    print("TEST 3: SAME TASK DOUBLE ACQUIRE -> REJECT")
    print("-" * 70)

    try:
        router.acquire(
            "TASK-ULTRA-01"
        )

    except LeaderLeaseError:
        print(
            "Duplicate leader lease rejected: PASS ✅"
        )

    else:
        raise AssertionError(
            "Same task acquired two leader leases."
        )

    router.release(
        "TASK-ULTRA-01"
    )

    print()

    # ======================================================================
    # TEST 4
    # ======================================================================

    print("-" * 70)
    print("TEST 4: ULTRA FAILURE -> NEXT HEALTHY ULTRA")
    print("-" * 70)

    first = router.acquire(
        "TASK-FAIL-01"
    )

    print(
        "First Ultra account:",
        first.account_id,
    )

    router.fail_current_leader(
        "TASK-FAIL-01",
        reason="synthetic_primary_failure",
    )

    second = router.acquire(
        "TASK-FAIL-02"
    )

    print(
        "Next Ultra account :",
        second.account_id,
    )

    if second.account_id != "OR-02":
        raise AssertionError(
            "Runtime-failed OR-01 was not skipped."
        )

    if second.tier != PRIMARY_TIER:
        raise AssertionError(
            "Router failed over to Super too early."
        )

    print(
        "Runtime failure survives health refresh: PASS ✅"
    )

    print(
        "Ultra account rotation: PASS ✅"
    )
    print()

    router.release(
        "TASK-FAIL-02"
    )

    # ======================================================================
    # TEST 5
    # ======================================================================

    print("-" * 70)
    print("TEST 5: ULTRA EXHAUSTION -> SUPER FAILOVER")
    print("-" * 70)

    # OR-01 already failed in TEST 4.
    #
    # Fail OR-02, OR-03, OR-04.
    for index in range(3):

        task_id = (
            f"TASK-ULTRA-EXHAUST-{index + 1}"
        )

        lease = router.acquire(
            task_id
        )

        if lease.tier != PRIMARY_TIER:
            raise AssertionError(
                "Expected Ultra during exhaustion."
            )

        print(
            "Failing Ultra account:",
            lease.account_id,
        )

        router.fail_current_leader(
            task_id,
            reason="synthetic_ultra_exhaustion",
        )

    super_lease = router.acquire(
        "TASK-SUPER-01"
    )

    print(
        "Failover account:",
        super_lease.account_id,
    )

    print(
        "Failover model  :",
        super_lease.model,
    )

    print(
        "Failover tier   :",
        super_lease.tier,
    )

    if super_lease.tier != FAILOVER_TIER:
        raise AssertionError(
            "Ultra exhaustion did not trigger Super."
        )

    if super_lease.model != FAILOVER_MODEL:
        raise AssertionError(
            "Wrong Super model."
        )

    if super_lease.account_id != "OR-01":
        raise AssertionError(
            "Unexpected first Super account."
        )

    router.release(
        "TASK-SUPER-01"
    )

    print(
        "Ultra -> Super failover: PASS ✅"
    )
    print()

    # ======================================================================
    # TEST 6
    # ======================================================================

    print("-" * 70)
    print("TEST 6: SUPER FAILURE -> NEXT SUPER")
    print("-" * 70)

    super_first = router.acquire(
        "TASK-SUPER-ROTATE-01"
    )

    print(
        "First Super account:",
        super_first.account_id,
    )

    if super_first.account_id != "OR-01":
        raise AssertionError(
            "Unexpected first Super account in rotation."
        )

    router.fail_current_leader(
        "TASK-SUPER-ROTATE-01",
        reason="synthetic_super_failure",
    )

    super_second = router.acquire(
        "TASK-SUPER-ROTATE-02"
    )

    print(
        "Next Super account :",
        super_second.account_id,
    )

    if super_second.account_id != "OR-02":
        raise AssertionError(
            "Router did not move to next Super account."
        )

    router.release(
        "TASK-SUPER-ROTATE-02"
    )

    print(
        "Super account rotation: PASS ✅"
    )
    print()

    # ======================================================================
    # TEST 7
    # ======================================================================

    print("-" * 70)
    print("TEST 7: TOTAL LEADER EXHAUSTION -> SAFE STOP")
    print("-" * 70)

    # IMPORTANT:
    # OR-01 is already runtime-failed for Super.
    # OR-02 was only USED in TEST 6, not failed.
    #
    # Therefore we must explicitly fail OR-02 before trying OR-03.
    final_super_1 = router.acquire(
        "TASK-SUPER-EXHAUST-01"
    )

    print(
        "Final Super failure #1:",
        final_super_1.account_id,
    )

    if final_super_1.account_id != "OR-02":
        raise AssertionError(
            "Expected OR-02 as next Super account."
        )

    router.fail_current_leader(
        "TASK-SUPER-EXHAUST-01",
        reason="synthetic_super_exhaustion",
    )

    final_super_2 = router.acquire(
        "TASK-SUPER-EXHAUST-02"
    )

    print(
        "Final Super failure #2:",
        final_super_2.account_id,
    )

    if final_super_2.account_id != "OR-03":
        raise AssertionError(
            "Expected OR-03 as final Super account."
        )

    router.fail_current_leader(
        "TASK-SUPER-EXHAUST-02",
        reason="synthetic_total_exhaustion",
    )

    try:
        router.acquire(
            "TASK-NO-LEADER"
        )

    except LeaderUnavailable as exc:
        print(
            "No leader available:"
        )

        print(
            f"  {exc}"
        )

        print(
            "SAFE STOP condition: PASS ✅"
        )

    else:
        raise AssertionError(
            "Router acquired a leader after total exhaustion."
        )

    print()

    # ======================================================================
    # TEST 8
    # ======================================================================

    print("-" * 70)
    print("TEST 8: RUNTIME FAILURE PERSISTENCE")
    print("-" * 70)

    snapshot = router.snapshot()

    expected_ultra_failures = {
        "OR-01",
        "OR-02",
        "OR-03",
        "OR-04",
    }

    expected_super_failures = {
        "OR-01",
        "OR-02",
        "OR-03",
    }

    actual_ultra_failures = set(
        snapshot[
            "primary_runtime_failed"
        ]
    )

    actual_super_failures = set(
        snapshot[
            "failover_runtime_failed"
        ]
    )

    if not expected_ultra_failures.issubset(
        actual_ultra_failures
    ):
        raise AssertionError(
            "Primary runtime failure history is incomplete."
        )

    if not expected_super_failures.issubset(
        actual_super_failures
    ):
        raise AssertionError(
            "Super runtime failure history is incomplete."
        )

    restored = LeaderRouter(
        profiles_file=router.profiles_file,
        health_file=router.health_file,
        state_file=state_file,
    )

    restored_snapshot = (
        restored.snapshot()
    )

    if not expected_ultra_failures.issubset(
        set(
            restored_snapshot[
                "primary_runtime_failed"
            ]
        )
    ):
        raise AssertionError(
            "Ultra runtime failures were not persisted."
        )

    if not expected_super_failures.issubset(
        set(
            restored_snapshot[
                "failover_runtime_failed"
            ]
        )
    ):
        raise AssertionError(
            "Super runtime failures were not persisted."
        )

    print(
        "Ultra runtime failures persisted: PASS ✅"
    )

    print(
        "Super runtime failures persisted: PASS ✅"
    )

    print(
        "Failure history entries:",
        restored_snapshot[
            "failure_history_count"
        ],
    )

    print(
        "Snapshot consistency: PASS ✅"
    )
    print()

    # ======================================================================
    # Cleanup
    # ======================================================================

    for path in synthetic_files:
        if path.exists():
            path.unlink()

    print("=" * 70)
    print("LEADER ROUTER TEST PASSED ✅")
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
        print("LEADER ROUTER TEST FAILED ❌")
        print("=" * 70)
        print(
            f"{type(exc).__name__}: {exc}"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )