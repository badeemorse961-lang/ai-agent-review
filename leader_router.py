from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from config_registry import (
    REGISTRY_FILE,
    RegistryError,
    load_registry,
    validate_registry,
)


# ============================================================================
# LEADER ROUTER v4
#
# Authoritative static configuration comes only from config/registry.json.
# Runtime health and lease state remain local/mutable.
#
# Configuration
#      +
# External health
#      +
# Runtime failures
#      +
# Active leases
#      ↓
# Effective availability
#      ↓
# Ultra primary
#      ↓
# Super failover
#      ↓
# SAFE STOP
# ============================================================================


BASE_DIR = Path(__file__).resolve().parent
LEADER_HEALTH_FILE = BASE_DIR / "leader_health.json"
ROUTER_STATE_FILE = BASE_DIR / "leader_router_state.json"

PRIMARY_TIER = "ULTRA"
FAILOVER_TIER = "SUPER"


# Deprecated compatibility names. Profiles are no longer authoritative.
LEADER_PROFILES_FILE = BASE_DIR / "leader_profiles.json"


# ============================================================================
# Exceptions
# ============================================================================


class LeaderRouterError(Exception):
    """Base leader router error."""


class LeaderConfigurationError(LeaderRouterError):
    """Invalid leader configuration."""


class LeaderUnavailable(LeaderRouterError):
    """No eligible leader account is available."""


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


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}"
    )

    try:
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise LeaderConfigurationError(
            f"Required JSON file is missing: {path}"
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LeaderConfigurationError(
            f"Cannot read JSON file: {path}"
        ) from exc

    if not isinstance(payload, dict):
        raise LeaderConfigurationError(
            f"JSON root must be an object: {path}"
        )

    return payload


# ============================================================================
# Leader Router
# ============================================================================


class LeaderRouter:
    """
    Authoritative leader router.

    Static configuration is loaded from config/registry.json.
    leader_profiles.json is never consulted for routing decisions.
    """

    def __init__(
        self,
        health_file: Path = LEADER_HEALTH_FILE,
        state_file: Path = ROUTER_STATE_FILE,
        registry_file: Path = REGISTRY_FILE,
        # Compatibility-only argument. It is intentionally ignored.
        profiles_file: Optional[Path] = None,
    ) -> None:
        del profiles_file

        self.health_file = health_file
        self.state_file = state_file
        self.registry_file = registry_file

        self._lock = threading.RLock()

        self.provider = ""
        self.primary_model = ""
        self.failover_model = ""
        self.primary_pool: List[str] = []
        self.failover_pool: List[str] = []

        self.external_healthy_by_model: Dict[str, Set[str]] = {}
        self.external_failed_by_model: Dict[str, Set[str]] = {}
        self.runtime_failed_by_model: Dict[str, Set[str]] = {}
        self.leases: Dict[str, LeaderLease] = {}
        self.failure_history: List[Dict[str, Any]] = []
        self.active_tier: Optional[str] = None
        self.active_account: Optional[str] = None

        self._load_registry()
        self._load_state()
        self.refresh_health()
        self._normalize_state()
        self._save_state()

    # ----------------------------------------------------------------------
    # Authoritative registry
    # ----------------------------------------------------------------------

    def _load_registry(self) -> None:
        try:
            if self.registry_file == REGISTRY_FILE:
                registry = validate_registry()
            else:
                registry = load_registry_from_path(self.registry_file)
        except (RegistryError, LeaderConfigurationError) as exc:
            raise LeaderConfigurationError(
                f"Invalid leader registry: {exc}"
            ) from exc

        architecture = registry.get("architecture")
        if not isinstance(architecture, dict):
            raise LeaderConfigurationError(
                "Registry is missing architecture."
            )

        leader = architecture.get("leader")
        if not isinstance(leader, dict):
            raise LeaderConfigurationError(
                "Registry is missing leader configuration."
            )

        provider = leader.get("provider")
        primary_model = leader.get("primary_model")
        failover_model = leader.get("failover_model")
        primary_pool = leader.get("primary_pool")
        failover_pool = leader.get("failover_pool")

        if not all(isinstance(value, str) and value.strip() for value in [
            provider,
            primary_model,
            failover_model,
        ]):
            raise LeaderConfigurationError(
                "Leader provider and models must be non-empty strings."
            )

        if not isinstance(primary_pool, list) or (not primary_pool and self.registry_file != REGISTRY_FILE):
            raise LeaderConfigurationError(
                "Leader primary pool must be a non-empty list."
            )

        if not isinstance(failover_pool, list) or (not failover_pool and self.registry_file != REGISTRY_FILE):
            raise LeaderConfigurationError(
                "Leader failover pool must be a non-empty list."
            )

        self.provider = provider
        self.primary_model = primary_model
        self.failover_model = failover_model
        self.primary_pool = unique_strings(primary_pool, "leader.primary_pool")
        self.failover_pool = unique_strings(
            failover_pool,
            "leader.failover_pool",
        )

    # ----------------------------------------------------------------------
    # External health
    # ----------------------------------------------------------------------

    def refresh_health(self) -> None:
        """Refresh external health while preserving runtime failures."""
        health = read_json(self.health_file)
        configured_by_model = {
            self.primary_model: set(self.primary_pool),
            self.failover_model: set(self.failover_pool),
        }

        declared_provider = health.get("provider")
        if declared_provider is not None and declared_provider != self.provider:
            raise LeaderConfigurationError(
                "Leader health provider does not match the authoritative registry"
            )

        healthy_by_model: Dict[str, Set[str]] = {}
        failed_by_model: Dict[str, Set[str]] = {}

        def add_status(
            model: str,
            account_id: str,
            healthy: bool,
        ) -> None:
            if model not in configured_by_model:
                return
            if account_id not in configured_by_model[model]:
                return
            if healthy:
                healthy_by_model.setdefault(model, set()).add(account_id)
            else:
                failed_by_model.setdefault(model, set()).add(account_id)

        mappings = [
            ("Ultra", self.primary_model),
            ("ultra", self.primary_model),
            ("Super", self.failover_model),
            ("super", self.failover_model),
        ]

        for key, model in mappings:
            section = health.get(key)
            if not isinstance(section, dict):
                continue
            section_provider = section.get("provider")
            if section_provider is not None and section_provider != self.provider:
                continue

            healthy = section.get("healthy")
            failed = section.get("failed")

            if isinstance(healthy, list):
                for account_id in healthy:
                    if isinstance(account_id, str):
                        add_status(model, account_id, True)

            if isinstance(failed, list):
                for account_id in failed:
                    if isinstance(account_id, str):
                        add_status(model, account_id, False)

        models = health.get("models")
        if isinstance(models, dict):
            for model, section in models.items():
                if model not in configured_by_model or not isinstance(section, dict):
                    continue
                section_provider = section.get("provider")
                section_model = section.get("model")
                if section_provider is not None and section_provider != self.provider:
                    continue
                if section_model is not None and section_model != model:
                    continue

                healthy = section.get("healthy")
                failed = section.get("failed")

                if isinstance(healthy, list):
                    for account_id in healthy:
                        if isinstance(account_id, str):
                            add_status(model, account_id, True)

                if isinstance(failed, list):
                    for account_id in failed:
                        if isinstance(account_id, str):
                            add_status(model, account_id, False)

        results = health.get("results")
        if isinstance(results, dict):
            status_values = {
                "HEALTHY",
                "READY",
                "VALID",
                "OK",
                "AVAILABLE",
            }

            for result_key, result in results.items():
                if not isinstance(result_key, str) or not isinstance(result, dict):
                    continue
                account_id = result.get("account_id") or result.get("connection_id")
                if not isinstance(account_id, str):
                    account_id = result_key.split(":", 1)[0]
                if not isinstance(account_id, str):
                    continue

                result_provider = result.get("provider")
                if result_provider is not None and result_provider != self.provider:
                    continue
                result_model = result.get("model")
                result_tier = result.get("tier")
                if result_model is not None and result_model not in configured_by_model:
                    continue
                if result_model is not None and account_id not in configured_by_model[result_model]:
                    continue
                if result_tier is not None:
                    tier_model = {
                        "ultra": self.primary_model,
                        "Ultra": self.primary_model,
                        "super": self.failover_model,
                        "Super": self.failover_model,
                    }.get(result_tier)
                    if tier_model is None:
                        continue
                    if result_model is not None and result_model != tier_model:
                        continue
                    result_model = tier_model

                for key, model in [
                    ("ultra", self.primary_model),
                    ("Ultra", self.primary_model),
                    ("super", self.failover_model),
                    ("Super", self.failover_model),
                ]:
                    status = result.get(key)
                    if isinstance(status, str):
                        add_status(
                            model,
                            account_id,
                            status.upper() in status_values,
                        )

                status = result.get("status")
                healthy_flag = result.get("healthy")
                if isinstance(status, str) and result_model is not None:
                    add_status(
                        result_model,
                        account_id,
                        status.upper() in status_values,
                    )
                elif isinstance(healthy_flag, bool) and result_model is not None:
                    add_status(result_model, account_id, healthy_flag)

        accounts = health.get("accounts")
        if isinstance(accounts, list):
            status_values = {
                "HEALTHY",
                "READY",
                "VALID",
                "OK",
                "AVAILABLE",
            }

            for account in accounts:
                if not isinstance(account, dict):
                    continue

                account_id = account.get("id") or account.get("account_id")
                if not isinstance(account_id, str):
                    continue
                account_provider = account.get("provider")
                if account_provider is not None and account_provider != self.provider:
                    continue

                for key, model in [
                    ("ultra", self.primary_model),
                    ("Ultra", self.primary_model),
                    ("super", self.failover_model),
                    ("Super", self.failover_model),
                ]:
                    section = account.get(key)
                    if isinstance(section, dict):
                        section_provider = section.get("provider")
                        if section_provider is not None and section_provider != self.provider:
                            continue
                        section_model = section.get("model")
                        if section_model is not None and section_model != model:
                            continue
                        status = section.get("status")
                        if isinstance(section.get("healthy"), bool):
                            add_status(model, account_id, section["healthy"])
                    else:
                        status = section

                    if isinstance(status, str):
                        add_status(
                            model,
                            account_id,
                            status.upper() in status_values,
                        )

        for model, failed in failed_by_model.items():
            healthy_by_model.setdefault(model, set()).difference_update(failed)

        self.external_healthy_by_model = healthy_by_model
        self.external_failed_by_model = failed_by_model

    # ----------------------------------------------------------------------
    # Runtime state
    # ----------------------------------------------------------------------

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return

        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        configured_by_model = {
            self.primary_model: set(self.primary_pool),
            self.failover_model: set(self.failover_pool),
        }

        runtime_failed = payload.get("runtime_failed_by_model")
        if isinstance(runtime_failed, dict):
            for model, accounts in runtime_failed.items():
                if model not in configured_by_model or not isinstance(accounts, list):
                    continue
                self.runtime_failed_by_model[model] = {
                    account
                    for account in accounts
                    if isinstance(account, str)
                    and account in configured_by_model[model]
                }

        leases = payload.get("leases")
        if isinstance(leases, dict):
            for task_id, item in leases.items():
                if not isinstance(task_id, str) or not isinstance(item, dict):
                    continue

                try:
                    leased_at = float(item["leased_at"])
                except (KeyError, TypeError, ValueError):
                    continue
                provider = item.get("provider")
                account_id = item.get("account_id")
                model = item.get("model")
                tier = item.get("tier")
                saved_task_id = item.get("task_id")
                if not all(isinstance(value, str) and value.strip() for value in [
                    provider,
                    account_id,
                    model,
                    tier,
                    saved_task_id,
                ]):
                    continue
                if not math.isfinite(leased_at) or leased_at < 0:
                    continue

                lease = LeaderLease(
                    provider=provider,
                    account_id=account_id,
                    model=model,
                    tier=tier,
                    task_id=saved_task_id,
                    leased_at=leased_at,
                )
                if lease.task_id == task_id:
                    self.leases[task_id] = lease

        history = payload.get("failure_history")
        if isinstance(history, list):
            self.failure_history = [
                item for item in history if isinstance(item, dict)
            ]

        active_tier = payload.get("active_tier")
        if isinstance(active_tier, str):
            self.active_tier = active_tier

        active_account = payload.get("active_account")
        if isinstance(active_account, str):
            self.active_account = active_account

    def _normalize_state(self) -> None:
        valid: Dict[str, LeaderLease] = {}
        used_accounts: Set[str] = set()
        configured_by_tier = {
            PRIMARY_TIER: (self.primary_model, set(self.primary_pool)),
            FAILOVER_TIER: (self.failover_model, set(self.failover_pool)),
        }

        for task_id, lease in self.leases.items():
            tier_config = configured_by_tier.get(lease.tier)
            if tier_config is None:
                continue
            expected_model, configured = tier_config
            if lease.account_id not in configured:
                continue
            if lease.account_id in used_accounts:
                continue
            if lease.provider != self.provider:
                continue
            if lease.model != expected_model:
                continue
            if lease.task_id != task_id:
                continue
            if not math.isfinite(lease.leased_at) or lease.leased_at < 0:
                continue

            valid[task_id] = lease
            used_accounts.add(lease.account_id)

        self.leases = valid

        if self.active_account is not None:
            active_lease = next(
                (
                    lease
                    for lease in self.leases.values()
                    if lease.account_id == self.active_account
                    and lease.tier == self.active_tier
                ),
                None,
            )
            if active_lease is None:
                self.active_tier = None
                self.active_account = None
        elif self.active_tier is not None:
            self.active_tier = None

        if not self.leases:
            self.active_tier = None
            self.active_account = None

    def _save_state(self) -> None:
        with self._lock:
            atomic_write_json(
                self.state_file,
                {
                    "version": 4,
                    "updated_at": time.time(),
                    "registry_file": str(self.registry_file),
                    "provider": self.provider,
                    "primary_model": self.primary_model,
                    "failover_model": self.failover_model,
                    "primary_pool": list(self.primary_pool),
                    "failover_pool": list(self.failover_pool),
                    "external_healthy_by_model": {
                        model: sorted(accounts)
                        for model, accounts in self.external_healthy_by_model.items()
                    },
                    "external_failed_by_model": {
                        model: sorted(accounts)
                        for model, accounts in self.external_failed_by_model.items()
                    },
                    "runtime_failed_by_model": {
                        model: sorted(accounts)
                        for model, accounts in self.runtime_failed_by_model.items()
                    },
                    "active_tier": self.active_tier,
                    "active_account": self.active_account,
                    "leases": {
                        task_id: lease.to_dict()
                        for task_id, lease in self.leases.items()
                    },
                    "failure_history": list(self.failure_history),
                },
            )

    # ----------------------------------------------------------------------
    # Effective availability
    # ----------------------------------------------------------------------

    def _effective_pool(self, tier: str) -> List[str]:
        if tier == PRIMARY_TIER:
            model = self.primary_model
            configured = self.primary_pool
        elif tier == FAILOVER_TIER:
            model = self.failover_model
            configured = self.failover_pool
        else:
            raise LeaderConfigurationError(f"Unknown tier: {tier}")

        external_healthy = self.external_healthy_by_model.get(model, set())
        external_failed = self.external_failed_by_model.get(model, set())
        runtime_failed = self.runtime_failed_by_model.get(model, set())
        leased_accounts = {lease.account_id for lease in self.leases.values()}

        return [
            account_id
            for account_id in configured
            if account_id in external_healthy
            and account_id not in external_failed
            and account_id not in runtime_failed
            and account_id not in leased_accounts
        ]

    def active_pool(self, tier: str) -> List[str]:
        with self._lock:
            self.refresh_health()
            return self._effective_pool(tier)

    # ----------------------------------------------------------------------
    # Acquire / release
    # ----------------------------------------------------------------------

    def acquire(self, task_id: str) -> LeaderLease:
        if not isinstance(task_id, str) or not task_id.strip():
            raise LeaderLeaseError("task_id must be a non-empty string.")

        with self._lock:
            if task_id in self.leases:
                raise LeaderLeaseError(
                    f"Task already owns a leader lease: {task_id}"
                )

            self.refresh_health()

            for tier, model in [
                (PRIMARY_TIER, self.primary_model),
                (FAILOVER_TIER, self.failover_model),
            ]:
                candidates = self._effective_pool(tier)
                if not candidates:
                    continue

                account_id = candidates[0]
                lease = LeaderLease(
                    provider=self.provider,
                    account_id=account_id,
                    model=model,
                    tier=tier,
                    task_id=task_id,
                    leased_at=time.time(),
                )

                self.leases[task_id] = lease
                self.active_tier = tier
                self.active_account = account_id
                self._save_state()
                return lease

            self.active_tier = None
            self.active_account = None
            self._save_state()

            raise LeaderUnavailable(
                "No healthy Ultra or Super leader account is available."
            )

    def release(self, task_id: str) -> LeaderLease:
        with self._lock:
            lease = self.leases.pop(task_id, None)
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
    # Runtime failure / health
    # ----------------------------------------------------------------------

    def fail_current_leader(
        self,
        task_id: str,
        reason: str = "runtime_failure",
    ) -> LeaderLease:
        with self._lock:
            lease = self.leases.get(task_id)
            if lease is None:
                raise LeaderLeaseError(
                    f"No active leader lease for task: {task_id}"
                )

            self.runtime_failed_by_model.setdefault(lease.model, set()).add(
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

            self.leases.pop(task_id, None)
            if not self.leases:
                self.active_tier = None
                self.active_account = None

            self._save_state()
            return lease

    def mark_healthy(self, account_id: str, tier: str) -> None:
        if not isinstance(account_id, str) or not account_id.strip():
            raise LeaderConfigurationError(
                "account_id must be a non-empty string."
            )

        with self._lock:
            if tier == PRIMARY_TIER:
                model = self.primary_model
            elif tier == FAILOVER_TIER:
                model = self.failover_model
            else:
                raise LeaderConfigurationError(f"Unknown tier: {tier}")

            configured = set(self.primary_pool) | set(self.failover_pool)
            if account_id not in configured:
                raise LeaderConfigurationError(
                    f"Unknown leader connection: {account_id}"
                )

            self.runtime_failed_by_model.setdefault(model, set()).discard(
                account_id
            )
            self.external_failed_by_model.setdefault(model, set()).discard(
                account_id
            )
            self.external_healthy_by_model.setdefault(model, set()).add(
                account_id
            )
            self._save_state()

    def clear_runtime_failures(self) -> None:
        with self._lock:
            self.runtime_failed_by_model = {}
            self._save_state()

    # ----------------------------------------------------------------------
    # Snapshot / reset
    # ----------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            self.refresh_health()
            return {
                "version": 4,
                "registry_file": str(self.registry_file),
                "provider": self.provider,
                "primary_model": self.primary_model,
                "failover_model": self.failover_model,
                "primary_configured": list(self.primary_pool),
                "primary_active": self._effective_pool(PRIMARY_TIER),
                "primary_external_failed": sorted(
                    self.external_failed_by_model.get(self.primary_model, set())
                ),
                "primary_runtime_failed": sorted(
                    self.runtime_failed_by_model.get(self.primary_model, set())
                ),
                "failover_configured": list(self.failover_pool),
                "failover_active": self._effective_pool(FAILOVER_TIER),
                "failover_external_failed": sorted(
                    self.external_failed_by_model.get(self.failover_model, set())
                ),
                "failover_runtime_failed": sorted(
                    self.runtime_failed_by_model.get(self.failover_model, set())
                ),
                "active_tier": self.active_tier,
                "active_account": self.active_account,
                "leases": {
                    task_id: lease.to_dict()
                    for task_id, lease in self.leases.items()
                },
                "failure_history_count": len(self.failure_history),
            }

    def reset_runtime(self) -> None:
        with self._lock:
            self.leases = {}
            self.failure_history = []
            self.runtime_failed_by_model = {}
            self.active_tier = None
            self.active_account = None
            self._save_state()


# ============================================================================
# Helpers
# ============================================================================


def unique_strings(values: List[Any], field: str) -> List[str]:
    result: List[str] = []
    seen: Set[str] = set()

    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise LeaderConfigurationError(
                f"{field} contains an invalid connection id."
            )
        if value in seen:
            raise LeaderConfigurationError(
                f"Duplicate connection id in {field}: {value}"
            )
        seen.add(value)
        result.append(value)

    return result


def load_registry_from_path(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise LeaderConfigurationError(
            f"Registry file is missing: {path}"
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LeaderConfigurationError(
            f"Cannot read registry file: {path}"
        ) from exc

    if not isinstance(payload, dict):
        raise LeaderConfigurationError(
            "Registry root must be an object."
        )

    return payload


# ============================================================================
# Synthetic test
# ============================================================================


def build_synthetic_health(router: LeaderRouter) -> Dict[str, Any]:
    return {
        "models": {
            router.primary_model: {
                "healthy": list(router.primary_pool),
                "failed": [],
            },
            router.failover_model: {
                "healthy": list(router.failover_pool),
                "failed": [],
            },
        }
    }


def synthetic_test() -> int:
    print("=" * 70)
    print("LEADER ROUTER REGISTRY SYNTHETIC TEST")
    print("=" * 70)
    print()

    state_file = BASE_DIR / "leader_router_test_state.json"
    health_file = BASE_DIR / "leader_router_test_health.json"

    for path in [state_file, health_file]:
        if path.exists():
            path.unlink()

    # The synthetic router still consumes the real authoritative registry.
    health_file.write_text(
        json.dumps(build_synthetic_health_for_registry(), indent=2),
        encoding="utf-8",
    )

    router = LeaderRouter(
        health_file=health_file,
        state_file=state_file,
    )

    # TEST 1: Registry-derived primary pool
    primary_pool = router.active_pool(PRIMARY_TIER)
    if primary_pool != router.primary_pool:
        raise AssertionError(
            "Active primary pool does not match healthy registry pool."
        )
    print(
        f"TEST 1 registry-driven primary pool ({len(primary_pool)}): PASS ✅"
    )

    # TEST 2: Primary acquisition
    first = router.acquire("TASK-ULTRA-01")
    if first.tier != PRIMARY_TIER or first.model != router.primary_model:
        raise AssertionError("Primary acquisition returned the wrong tier/model.")
    print("TEST 2 primary acquisition: PASS ✅")

    router.fail_current_leader("TASK-ULTRA-01")

    # TEST 3: Primary rotation
    second = router.acquire("TASK-ULTRA-02")
    if second.account_id == first.account_id:
        raise AssertionError("Primary rotation reused the failed account.")
    print("TEST 3 primary failure rotation: PASS ✅")

    router.release("TASK-ULTRA-02")

    # TEST 4: Exhaust primary runtime failures, then fail over.
    router.clear_runtime_failures()
    for index in range(len(router.primary_pool)):
        task_id = f"TASK-PRIMARY-EXHAUST-{index}"
        lease = router.acquire(task_id)
        if lease.tier != PRIMARY_TIER:
            raise AssertionError("Primary pool exhausted before expected point.")
        router.fail_current_leader(task_id)

    failover = router.acquire("TASK-SUPER-01")
    if failover.tier != FAILOVER_TIER or failover.model != router.failover_model:
        raise AssertionError("Failover did not select Super tier.")
    print("TEST 4 Ultra → Super failover: PASS ✅")

    router.fail_current_leader("TASK-SUPER-01")

    # Exhaust the remaining failover accounts.
    for index in range(len(router.failover_pool) - 1):
        task_id = f"TASK-FAILOVER-EXHAUST-{index}"
        lease = router.acquire(task_id)
        if lease.tier != FAILOVER_TIER:
            raise AssertionError("Failover pool did not remain available as expected.")
        router.fail_current_leader(task_id)

    try:
        router.acquire("TASK-SAFE-STOP")
    except LeaderUnavailable:
        print("TEST 5 complete exhaustion → SAFE STOP: PASS ✅")
    else:
        raise AssertionError("Expected SAFE STOP after complete leader exhaustion.")

    for path in [state_file, health_file]:
        if path.exists():
            path.unlink()

    print("=" * 70)
    print("LEADER ROUTER REGISTRY TEST PASSED ✅")
    print("=" * 70)
    return 0


def build_synthetic_health_for_registry() -> Dict[str, Any]:
    registry = validate_registry()
    leader = registry["architecture"]["leader"]
    return {
        "models": {
            leader["primary_model"]: {
                "healthy": list(leader["primary_pool"]),
                "failed": [],
            },
            leader["failover_model"]: {
                "healthy": list(leader["failover_pool"]),
                "failed": [],
            },
        }
    }


def main() -> int:
    try:
        return synthetic_test()
    except Exception as exc:
        print()
        print("=" * 70)
        print("LEADER ROUTER REGISTRY TEST FAILED ❌")
        print("=" * 70)
        print(f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
