from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
PROFILES_FILE = BASE_DIR / "leader_profiles.json"


PRIMARY_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
FAILOVER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


class LeaderFailover:
    """
    Model-aware leader failover manager.

    Strategy:

        Primary Ultra pool
            |
            v
        Next Ultra connection
            |
            v
        Super failover pool
            |
            v
        Next Super connection
            |
            v
        SAFE STOP
    """

    def __init__(self, profiles_file: Path):
        self.profiles_file = profiles_file
        self.data = self._load()

        self.architecture = self.data["architecture"]
        self.pools = self.data["pools"]
        self.runtime = self.data["runtime"]

        self.primary_pool = self.pools["primary"]
        self.failover_pool = self.pools["failover"]

        self._validate()

    # =========================================================
    # Persistence
    # =========================================================

    def _load(self) -> dict[str, Any]:
        if not self.profiles_file.exists():
            raise FileNotFoundError(
                f"Missing file: {self.profiles_file}"
            )

        with self.profiles_file.open(
            "r",
            encoding="utf-8",
        ) as f:
            return json.load(f)

    def _save(self) -> None:
        with self.profiles_file.open(
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                self.data,
                f,
                indent=2,
                ensure_ascii=False,
            )

    # =========================================================
    # Validation
    # =========================================================

    def _validate(self) -> None:
        primary_model = self.primary_pool["model"]
        failover_model = self.failover_pool["model"]

        if primary_model != PRIMARY_MODEL:
            raise RuntimeError(
                "Invalid primary leader model."
            )

        if failover_model != FAILOVER_MODEL:
            raise RuntimeError(
                "Invalid failover leader model."
            )

        if not self.primary_pool["connections"]:
            raise RuntimeError(
                "Primary leader pool is empty."
            )

        if not self.failover_pool["connections"]:
            raise RuntimeError(
                "Failover leader pool is empty."
            )

        if self.runtime["active_tier"] not in {
            "primary",
            "failover",
            "safe_stop",
        }:
            raise RuntimeError(
                "Invalid runtime tier."
            )

        required_runtime_fields = {
            "active_tier",
            "active_connection",
            "active_model",
            "primary_index",
            "failover_index",
            "state",
            "failure_history",
        }

        missing = required_runtime_fields.difference(
            self.runtime.keys()
        )

        if missing:
            raise RuntimeError(
                "Missing runtime fields: "
                + ", ".join(sorted(missing))
            )

    # =========================================================
    # State
    # =========================================================

    def current_connection(self) -> str | None:
        return self.runtime.get("active_connection")

    def current_model(self) -> str | None:
        return self.runtime.get("active_model")

    def current_tier(self) -> str:
        return self.runtime["active_tier"]

    def state(self) -> str:
        return self.runtime["state"]

    def status(self) -> dict[str, Any]:
        return {
            "tier": self.current_tier(),
            "connection": self.current_connection(),
            "model": self.current_model(),
            "state": self.state(),
        }

    # =========================================================
    # Failure bookkeeping
    # =========================================================

    def _record_failure(
        self,
        connection: str | None,
        model: str | None,
        reason: str,
    ) -> None:
        if connection is None:
            return

        self.runtime["failure_history"].append(
            {
                "timestamp": datetime.now(
                    timezone.utc
                ).isoformat(),
                "tier": self.current_tier(),
                "connection": connection,
                "model": model,
                "reason": reason,
            }
        )

    # =========================================================
    # Candidate selection
    # =========================================================

    def _next_primary(self) -> str | None:
        pool = self.primary_pool["connections"]
        index = self.runtime["primary_index"]

        next_index = index + 1

        if next_index >= len(pool):
            return None

        self.runtime["primary_index"] = next_index

        return pool[next_index]

    def _next_failover(self) -> str | None:
        pool = self.failover_pool["connections"]
        index = self.runtime["failover_index"]

        next_index = index + 1

        if next_index >= len(pool):
            return None

        self.runtime["failover_index"] = next_index

        return pool[next_index]

    # =========================================================
    # Activation
    # =========================================================

    def _activate_primary(
        self,
        connection: str,
    ) -> str:
        self.runtime["active_tier"] = "primary"
        self.runtime["active_connection"] = connection
        self.runtime["active_model"] = (
            self.primary_pool["model"]
        )
        self.runtime["state"] = "READY"

        self._save()

        return connection

    def _activate_failover(
        self,
        connection: str,
    ) -> str:
        self.runtime["active_tier"] = "failover"
        self.runtime["active_connection"] = connection
        self.runtime["active_model"] = (
            self.failover_pool["model"]
        )
        self.runtime["state"] = "READY"

        self._save()

        return connection

    def _activate_safe_stop(self) -> None:
        self.runtime["active_tier"] = "safe_stop"
        self.runtime["active_connection"] = None
        self.runtime["active_model"] = None
        self.runtime["state"] = "SAFE_STOP"

        self._save()

    # =========================================================
    # Main failover operation
    # =========================================================

    def failover(
        self,
        reason: str = "unknown_failure",
    ) -> str | None:
        """
        Record current failure and move to the next
        valid leader connection.

        Order:

            Ultra -> next Ultra
            Ultra exhausted -> Super OR-01
            Super -> next Super
            Super exhausted -> SAFE_STOP
        """

        current_connection = self.current_connection()
        current_model = self.current_model()

        self._record_failure(
            connection=current_connection,
            model=current_model,
            reason=reason,
        )

        # -----------------------------------------------------
        # PRIMARY ULTRA -> NEXT ULTRA
        # -----------------------------------------------------

        if self.current_tier() == "primary":
            candidate = self._next_primary()

            if candidate is not None:
                return self._activate_primary(
                    candidate
                )

            # All Ultra connections exhausted.
            # Start Super from its first connection.
            self.runtime["failover_index"] = 0

            failover_connections = (
                self.failover_pool["connections"]
            )

            if failover_connections:
                return self._activate_failover(
                    failover_connections[0]
                )

        # -----------------------------------------------------
        # SUPER -> NEXT SUPER
        # -----------------------------------------------------

        elif self.current_tier() == "failover":
            candidate = self._next_failover()

            if candidate is not None:
                return self._activate_failover(
                    candidate
                )

        # -----------------------------------------------------
        # COMPLETE EXHAUSTION
        # -----------------------------------------------------

        self._activate_safe_stop()

        return None

    # =========================================================
    # Reset
    # =========================================================

    def reset(self) -> str:
        """
        Reset the leadership cycle back to Ultra OR-01.
        """

        primary_connections = (
            self.primary_pool["connections"]
        )

        if not primary_connections:
            raise RuntimeError(
                "Cannot reset: primary pool is empty."
            )

        self.runtime["primary_index"] = 0
        self.runtime["failover_index"] = 0

        self.runtime["active_tier"] = "primary"
        self.runtime["active_connection"] = (
            primary_connections[0]
        )
        self.runtime["active_model"] = (
            self.primary_pool["model"]
        )
        self.runtime["state"] = "READY"

        self.runtime["failure_history"] = []

        self._save()

        return self.runtime["active_connection"]


def main() -> int:
    manager = LeaderFailover(
        PROFILES_FILE
    )

    print("=" * 70)
    print("MODEL-AWARE LEADER FAILOVER TEST")
    print("=" * 70)

    # =========================================================
    # Configuration
    # =========================================================

    print()
    print("PRIMARY MODEL:")
    print(
        f"  {manager.primary_pool['model']}"
    )

    print(
        "PRIMARY POOL "
        f"({len(manager.primary_pool['connections'])}):"
    )

    print(
        "  "
        + ", ".join(
            manager.primary_pool["connections"]
        )
    )

    print()
    print("FAILOVER MODEL:")
    print(
        f"  {manager.failover_pool['model']}"
    )

    print(
        "FAILOVER POOL "
        f"({len(manager.failover_pool['connections'])}):"
    )

    print(
        "  "
        + ", ".join(
            manager.failover_pool["connections"]
        )
    )

    # =========================================================
    # Initial state
    # =========================================================

    print()
    print("INITIAL STATE")

    print(
        f"  Tier       : "
        f"{manager.current_tier()}"
    )

    print(
        f"  Connection : "
        f"{manager.current_connection()}"
    )

    print(
        f"  Model      : "
        f"{manager.current_model()}"
    )

    print(
        f"  State      : "
        f"{manager.state()}"
    )

    print()
    print("-" * 70)

    # =========================================================
    # Exhaust Ultra connections WITHOUT crossing tiers
    # =========================================================

    primary_count = len(
        manager.primary_pool["connections"]
    )

    # We start on Ultra OR-01.
    # Ten failures move us through:
    #
    # OR-01 -> OR-02
    # ...
    # OR-10 -> OR-11
    #
    # The next failure is tested separately
    # as the Ultra -> Super transition.

    for step in range(primary_count - 1):
        previous_connection = (
            manager.current_connection()
        )

        previous_model = (
            manager.current_model()
        )

        next_connection = manager.failover(
            reason=(
                f"simulated_primary_failure_"
                f"{step + 1}"
            )
        )

        print(
            f"ULTRA {step + 1:02d}: "
            f"{previous_connection} "
            f"[{previous_model}]"
            f" -> "
            f"{next_connection}"
        )

        if manager.current_tier() != "primary":
            print(
                "ERROR: Unexpected tier transition "
                "during Ultra pool test."
            )
            return 1

        if manager.current_model() != PRIMARY_MODEL:
            print(
                "ERROR: Unexpected model transition "
                "during Ultra pool test."
            )
            return 1

    # =========================================================
    # Explicit Ultra -> Super transition
    # =========================================================

    previous_connection = (
        manager.current_connection()
    )

    previous_model = (
        manager.current_model()
    )

    next_connection = manager.failover(
        reason="simulated_final_ultra_failure"
    )

    print(
        f"ULTRA -> SUPER: "
        f"{previous_connection} "
        f"[{previous_model}]"
        f" -> "
        f"{next_connection} "
        f"[{manager.current_model()}]"
    )

    print("-" * 70)

    # =========================================================
    # Verify Ultra -> Super transition
    # =========================================================

    if manager.current_tier() != "failover":
        print(
            "ERROR: Primary Ultra pool did not "
            "transition to Super failover."
        )
        return 1

    if manager.current_model() != FAILOVER_MODEL:
        print(
            "ERROR: Active model is not the "
            "expected Super model."
        )
        return 1

    if manager.current_connection() != (
        manager.failover_pool["connections"][0]
    ):
        print(
            "ERROR: Super failover did not start "
            "at the first connection."
        )
        return 1

    print(
        "PRIMARY POOL EXHAUSTED -> "
        "SUPER FAILOVER ACTIVATED ✅"
    )

    print(
        f"ACTIVE CONNECTION: "
        f"{manager.current_connection()}"
    )

    print(
        f"ACTIVE MODEL     : "
        f"{manager.current_model()}"
    )

    print("-" * 70)

    # =========================================================
    # Exhaust Super connections WITHOUT crossing
    # =========================================================

    failover_count = len(
        manager.failover_pool["connections"]
    )

    # We start on Super OR-01.
    # Ten failures move us through:
    #
    # OR-01 -> OR-02
    # ...
    # OR-10 -> OR-11
    #
    # The final failure is tested separately
    # as the Super -> SAFE STOP transition.

    for step in range(failover_count - 1):
        previous_connection = (
            manager.current_connection()
        )

        previous_model = (
            manager.current_model()
        )

        next_connection = manager.failover(
            reason=(
                f"simulated_failover_failure_"
                f"{step + 1}"
            )
        )

        print(
            f"SUPER {step + 1:02d}: "
            f"{previous_connection} "
            f"[{previous_model}]"
            f" -> "
            f"{next_connection}"
        )

        if manager.current_tier() != "failover":
            print(
                "ERROR: Unexpected tier transition "
                "during Super pool test."
            )
            return 1

        if manager.current_model() != FAILOVER_MODEL:
            print(
                "ERROR: Unexpected model transition "
                "during Super pool test."
            )
            return 1

    # =========================================================
    # Explicit Super -> SAFE STOP transition
    # =========================================================

    previous_connection = (
        manager.current_connection()
    )

    previous_model = (
        manager.current_model()
    )

    final_connection = manager.failover(
        reason="simulated_complete_leadership_exhaustion"
    )

    print(
        f"SUPER -> SAFE STOP: "
        f"{previous_connection} "
        f"[{previous_model}]"
        f" -> "
        f"{final_connection}"
    )

    print("-" * 70)

    # =========================================================
    # Verify SAFE STOP
    # =========================================================

    if final_connection is not None:
        print(
            "ERROR: A connection was returned "
            "after complete exhaustion."
        )
        return 1

    if manager.current_tier() != "safe_stop":
        print(
            "ERROR: SAFE STOP was not activated."
        )
        return 1

    if manager.state() != "SAFE_STOP":
        print(
            "ERROR: Runtime state is not SAFE_STOP."
        )
        return 1

    if manager.current_connection() is not None:
        print(
            "ERROR: Active connection still exists "
            "after SAFE STOP."
        )
        return 1

    if manager.current_model() is not None:
        print(
            "ERROR: Active model still exists "
            "after SAFE STOP."
        )
        return 1

    print()
    print(
        "SAFE STOP ACTIVATED ✅"
    )

    print(
        "No leader connections remain "
        "in this cycle."
    )

    # =========================================================
    # Failure history verification
    # =========================================================

    history_count = len(
        manager.runtime["failure_history"]
    )

    print()
    print(
        "FAILURE HISTORY ENTRIES: "
        f"{history_count}"
    )

    expected_failures = (
        primary_count + failover_count
    )

    if history_count != expected_failures:
        print(
            "ERROR: Unexpected failure history count."
        )
        print(
            f"Expected: {expected_failures}"
        )
        print(
            f"Actual  : {history_count}"
        )
        return 1

    # =========================================================
    # Reset
    # =========================================================

    print()

    reset_connection = manager.reset()

    print(
        f"RESET -> {reset_connection}"
    )

    print(
        f"Tier       : "
        f"{manager.current_tier()}"
    )

    print(
        f"Connection : "
        f"{manager.current_connection()}"
    )

    print(
        f"Model      : "
        f"{manager.current_model()}"
    )

    print(
        f"State      : "
        f"{manager.state()}"
    )

    # =========================================================
    # Reset validation
    # =========================================================

    if manager.current_tier() != "primary":
        print(
            "ERROR: Reset did not return "
            "to primary tier."
        )
        return 1

    if manager.current_connection() != (
        manager.primary_pool["connections"][0]
    ):
        print(
            "ERROR: Reset did not return "
            "to Ultra OR-01."
        )
        return 1

    if manager.current_model() != PRIMARY_MODEL:
        print(
            "ERROR: Reset did not restore "
            "Ultra model."
        )
        return 1

    if manager.state() != "READY":
        print(
            "ERROR: Reset did not restore READY state."
        )
        return 1

    if manager.runtime["failure_history"]:
        print(
            "ERROR: Reset did not clear "
            "failure history."
        )
        return 1

    print()
    print("=" * 70)
    print(
        "MODEL-AWARE FAILOVER TEST PASSED ✅"
    )
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())