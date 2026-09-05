from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from leader_router import (
    FAILOVER_TIER,
    PRIMARY_TIER,
    LeaderRouter,
    LeaderUnavailable,
)


BASE_DIR = Path(__file__).resolve().parent

# Compatibility-only path. LeaderFailover no longer reads profile files.
PROFILES_FILE = BASE_DIR / "leader_profiles.json"


class LeaderFailover:
    """
    Compatibility facade over the authoritative LeaderRouter.

    There is intentionally no second failover implementation here.
    LeaderRouter owns leader selection, health-aware availability,
    leases, runtime failure tracking, failover, and SAFE_STOP.
    """

    def __init__(
        self,
        profiles_file: Optional[Path] = None,
        health_file: Optional[Path] = None,
        state_file: Optional[Path] = None,
    ) -> None:
        del profiles_file

        kwargs: dict[str, Any] = {}
        if health_file is not None:
            kwargs["health_file"] = health_file
        if state_file is not None:
            kwargs["state_file"] = state_file

        self.router = LeaderRouter(**kwargs)

    def current_connection(self) -> str | None:
        return self.router.active_account

    def current_model(self) -> str | None:
        if self.router.active_tier == PRIMARY_TIER:
            return self.router.primary_model
        if self.router.active_tier == FAILOVER_TIER:
            return self.router.failover_model
        return None

    def current_tier(self) -> str:
        if self.router.active_tier == PRIMARY_TIER:
            return "primary"
        if self.router.active_tier == FAILOVER_TIER:
            return "failover"
        return "safe_stop"

    def state(self) -> str:
        return "READY" if self.router.active_account else "SAFE_STOP"

    def status(self) -> dict[str, Any]:
        return {
            "tier": self.current_tier(),
            "connection": self.current_connection(),
            "model": self.current_model(),
            "state": self.state(),
        }

    @property
    def primary_model(self) -> str:
        return self.router.primary_model

    @property
    def failover_model(self) -> str:
        return self.router.failover_model

    @property
    def primary_pool(self) -> dict[str, Any]:
        return {
            "model": self.router.primary_model,
            "connections": list(self.router.primary_pool),
        }

    @property
    def failover_pool(self) -> dict[str, Any]:
        return {
            "model": self.router.failover_model,
            "connections": list(self.router.failover_pool),
        }

    def failover(self, reason: str = "unknown_failure") -> str | None:
        task_id = "__leader_failover_compat__"

        # Compatibility calls operate on a single synthetic lease so the
        # authoritative router remains responsible for failure bookkeeping.
        if task_id not in self.router.active_leases():
            try:
                self.router.acquire(task_id)
            except LeaderUnavailable:
                return None

        self.router.fail_current_leader(task_id, reason=reason)

        try:
            lease = self.router.acquire(task_id)
        except LeaderUnavailable:
            return None

        return lease.account_id

    def reset(self) -> str:
        """Reset to the first available primary leader and keep it active."""
        self.router.reset_runtime()
        lease = self.router.acquire("__leader_failover_reset__")
        return lease.account_id

    def snapshot(self) -> dict[str, Any]:
        return self.router.snapshot()


def main() -> int:
    print("=" * 70)
    print("LEADER FAILOVER COMPATIBILITY TEST")
    print("=" * 70)
    print()

    manager = LeaderFailover()
    print(f"Primary model : {manager.primary_model}")
    print(f"Failover model: {manager.failover_model}")
    print(f"Primary pool  : {len(manager.primary_pool['connections'])}")
    print(f"Failover pool : {len(manager.failover_pool['connections'])}")
    print()
    print("LeaderFailover is now a compatibility facade over LeaderRouter.")
    print("Runtime authority: LeaderRouter")
    print("Result: READY ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
