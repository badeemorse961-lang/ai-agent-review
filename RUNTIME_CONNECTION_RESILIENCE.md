# Runtime Connection Resilience Policy

## Purpose

A transient provider, model, or individual-account failure must not unnecessarily block a task when another configured connection can produce a valid response.

## Core rule

The runtime success criterion is not whether a specific account is healthy at a previous health-check moment. The criterion is whether the runtime can obtain a valid, locally verifiable response from an eligible configured connection.

```text
Task
  ↓
Eligible connection
  ↓
Request
  ├─ valid response → continue
  └─ invalid / failed response
          ↓
     record runtime failure
          ↓
     exclude failed connection for the current runtime context
          ↓
     try next eligible connection
          ↓
     continue or SAFE_STOP when no eligible connection remains
```

## Failure categories

Runtime routing should distinguish at least:

- authentication failure;
- quota / credit exhaustion;
- rate limiting;
- connection timeout;
- provider/server error;
- invalid JSON or invalid response shape;
- locally rejected output.

These conditions are runtime evidence that should influence the next routing decision rather than automatically terminating the whole task.

## Health checks are advisory runtime input

A health-check result is a snapshot. It can become stale or change between checks.

Therefore:

```text
Health snapshot
      +
Runtime success/failure
      ↓
Effective availability
```

A connection that failed a previous check may later succeed, and a connection that passed a previous check may fail during the actual task.

## Model failover

For leader routing, failure of a connection while using the primary model must permit the router to continue through the configured primary pool and then the failover model/pool according to registry policy.

A successful failover response is sufficient to continue the current operation; a failed individual attempt is not itself a task-level failure when another eligible configured route remains.

## Worker failover

For required worker roles, a failed worker attempt should be recorded as a runtime failure and the router should attempt another eligible worker from the same role. Standby is used only according to the worker routing policy after required-role capacity is exhausted.

## Safety boundary

Resilience must not mean infinite retries or ignoring invalid output.

Every failed attempt must consume a finite eligible route and be recorded. The runtime must eventually reach a deterministic `SAFE_STOP` when no suitable configured connection remains or when validation cannot prove a safe result.

## Expansion requirement

Pool size is configuration, not architecture. Increasing account capacity (for example 11 → 20 → 50 → N) must increase the number of eligible runtime attempts without requiring a routing-architecture rewrite.

## Credential protection

Runtime resilience must never move, copy, print, or persist raw credentials. Local secret files remain protected local state and must not be deleted or overwritten by repository synchronization.
