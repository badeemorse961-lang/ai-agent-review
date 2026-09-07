from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

from leader_router import LeaderLease, LeaderRouter, LeaderUnavailable


SCHEMA_VERSION = 1
SAFE_STATES = {"BUILD", "CONTINUE", "MAINTAIN", "REPAIR"}
SAFETY_STOP_STATES = {"UNKNOWN", "CONFLICT"}


class CentralLeaderError(ValueError):
    """Base error raised by the Central Leader boundary."""


class LeaderPlanningSafetyStop(CentralLeaderError):
    """Raised when project evidence is not safe for autonomous planning."""


@dataclass(frozen=True)
class LeaderRequest:
    """Provider-independent request descriptor for the future model adapter."""

    provider: str
    account_id: str
    model: str
    tier: str
    task_id: str
    context: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "account_id": self.account_id,
            "model": self.model,
            "tier": self.tier,
            "task_id": self.task_id,
            "context": dict(self.context),
        }


@dataclass(frozen=True)
class LeaderResponse:
    """Untrusted model response captured before any execution decision."""

    payload: Any
    account_id: str
    model: str
    tier: str


class CentralLeader:
    """Guarded boundary between planning context and a leader model.

    The class deliberately separates four concerns:
    1. validate evidence-only context;
    2. acquire one available leader connection from the N-sized pool;
    3. optionally invoke a caller-supplied transport adapter;
    4. return untrusted planning output without granting execution authority.

    No provider SDK, secret loading, filesystem mutation, or command execution
    occurs here. The active connection is selected by ``LeaderRouter`` from
    ``config/registry.json`` and current runtime health.
    """

    def __init__(
        self,
        router: Optional[LeaderRouter] = None,
        transport: Optional[Callable[[LeaderRequest], Any]] = None,
    ) -> None:
        self.router = router or LeaderRouter()
        self.transport = transport

    def prepare(
        self,
        task_id: str,
        context: Mapping[str, Any],
    ) -> LeaderRequest:
        self._validate_context(context)
        lease = self.router.acquire(task_id)
        return self._request_from_lease(lease, task_id, context)

    def plan(
        self,
        task_id: str,
        context: Mapping[str, Any],
    ) -> LeaderResponse:
        """Obtain a single leader response through an injected adapter.

        The adapter is intentionally injected so tests can exercise routing and
        boundary semantics without network calls. A future provider adapter may
        perform the actual request, but its output remains untrusted here.
        """
        if self.transport is None:
            raise CentralLeaderError("No leader transport adapter is configured")

        request = self.prepare(task_id, context)
        try:
            payload = self.transport(request)
        except Exception as exc:  # transport failures are runtime failures
            self.router.fail_current_leader(task_id, reason=type(exc).__name__)
            raise

        lease = self.router.leases.get(task_id)
        if lease is None:
            raise CentralLeaderError("Leader lease disappeared during planning")

        return LeaderResponse(
            payload=payload,
            account_id=lease.account_id,
            model=lease.model,
            tier=lease.tier,
        )

    def release(self, task_id: str) -> LeaderLease:
        return self.router.release(task_id)

    @staticmethod
    def _validate_context(context: Mapping[str, Any]) -> None:
        if not isinstance(context, Mapping):
            raise CentralLeaderError("Leader context must be a mapping")

        authority = context.get("authority")
        if not isinstance(authority, Mapping):
            raise CentralLeaderError("Leader context is missing authority metadata")
        if authority.get("execution_authorized") is not False:
            raise CentralLeaderError("Leader context must not authorize execution")
        if authority.get("mutation_allowed") is not False:
            raise CentralLeaderError("Leader context must not permit mutation")
        if authority.get("source_contents_included") is not False:
            raise CentralLeaderError("Leader context must exclude raw source contents")

        project = context.get("project")
        if not isinstance(project, Mapping):
            raise CentralLeaderError("Leader context is missing project metadata")

        state = str(project.get("state") or "UNKNOWN")
        if state in SAFETY_STOP_STATES:
            raise LeaderPlanningSafetyStop(
                f"Project state {state} is a safety stop for autonomous leader planning"
            )
        if state not in SAFE_STATES:
            raise LeaderPlanningSafetyStop(
                f"Unsupported project state for autonomous leader planning: {state}"
            )
        if project.get("autonomous_start_allowed") is not True:
            raise LeaderPlanningSafetyStop(
                "Project evidence does not explicitly authorize autonomous leader planning"
            )

    @staticmethod
    def _request_from_lease(
        lease: LeaderLease,
        task_id: str,
        context: Mapping[str, Any],
    ) -> LeaderRequest:
        safe_context = json.loads(
            json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        return LeaderRequest(
            provider=lease.provider,
            account_id=lease.account_id,
            model=lease.model,
            tier=lease.tier,
            task_id=task_id,
            context=safe_context,
        )


def plan_with_leader(
    task_id: str,
    context: Mapping[str, Any],
    *,
    router: Optional[LeaderRouter] = None,
    transport: Optional[Callable[[LeaderRequest], Any]] = None,
) -> LeaderResponse:
    """Functional entry point for the Central Leader planning boundary."""
    leader = CentralLeader(router=router, transport=transport)
    return leader.plan(task_id, context)


if __name__ == "__main__":
    print("Central Leader boundary ready.")
