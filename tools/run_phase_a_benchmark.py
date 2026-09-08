from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from model_benchmark import RunResult, _aggregate_group, run_benchmark
from phase_a_candidate_inventory import (
    build_phase_a_candidates,
    discover_connection_inventory,
    inventory_summary,
)
from protected_secret_store import WindowsProtectedSecretStore


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = BASE_DIR / "benchmark_results.local.json"

_PROVIDER_FAILURES = {
    "HTTPError",
    "ConnectionError",
    "Timeout",
    "RequestException",
    "JSONDecodeError",
}
_SECRETSTORE_FAILURES = {"SecretStoreError"}


def _failure_category(result: RunResult) -> str:
    error = str(result.error or "")
    if not error:
        return "none"
    error_name = error.split(":", 1)[0].strip()
    if error_name in _SECRETSTORE_FAILURES:
        return "secret_store"
    if error_name in _PROVIDER_FAILURES:
        return "provider"
    return "benchmark"


def _safe_number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _mean_metric(groups: Sequence[Mapping[str, Any]], key: str) -> float:
    values = [_safe_number(item.get(key)) for item in groups]
    return round(mean(values), 4) if values else 0.0


def model_level_aggregate(results: Sequence[RunResult]) -> dict[str, Any]:
    """Macro-average each connection before comparing a model.

    This prevents a provider with many execution accounts from becoming a heavier
    model vote than a provider/model backed by fewer accounts.
    """
    by_model_connection: dict[tuple[str, str, str], list[RunResult]] = defaultdict(list)
    for result in results:
        by_model_connection[(result.candidate.provider, result.candidate.model, result.candidate.connection_id)].append(result)

    by_model: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for (provider, model, _connection_id), items in by_model_connection.items():
        summary = dict(_aggregate_group(items))
        summary["connection_id"] = items[0].candidate.connection_id
        by_model[(provider, model)].append(summary)

    output: dict[str, Any] = {}
    for (provider, model), groups in sorted(by_model.items()):
        output[f"{provider}:{model}"] = {
            "provider": provider,
            "model": model,
            "connections_tested": len(groups),
            "aggregation": "macro_average_over_connections",
            "pass_rate": _mean_metric(groups, "pass_rate"),
            "mean_score": _mean_metric(groups, "mean_score"),
            "median_score": _mean_metric(groups, "median_score"),
            "mean_latency_ms": _mean_metric(groups, "mean_latency_ms"),
            "reliability": _mean_metric(groups, "dimensions_reliability"),
            "consistency_rate": _mean_metric(groups, "consistency_rate"),
            "cost_usd": _mean_metric(groups, "cost_usd"),
            "hard_failures_mean_per_connection": _mean_metric(groups, "hard_fail_count"),
            "hard_failures_total": int(sum(int(_safe_number(item.get("hard_fail_count"))) for item in groups)),
        }
    return output


def _model_group_with_reliability(items: Sequence[RunResult]) -> dict[str, Any]:
    summary = dict(_aggregate_group(list(items)))
    summary["dimensions_reliability"] = _safe_number(summary.get("dimensions", {}).get("reliability")) if isinstance(summary.get("dimensions"), Mapping) else 0.0
    return summary


def connection_level_aggregate(results: Sequence[RunResult]) -> dict[str, Any]:
    groups: dict[tuple[str, str], list[RunResult]] = defaultdict(list)
    for result in results:
        groups[(result.candidate.provider, result.candidate.connection_id)].append(result)

    output: dict[str, Any] = {}
    for (provider, connection_id), items in sorted(groups.items()):
        categories = Counter(_failure_category(item) for item in items)
        failure_signatures = Counter(
            (_failure_category(item), str(item.error or ""))
            for item in items
            if item.error
        )
        repeated = sum(max(0, count - 1) for count in failure_signatures.values())
        attempts = len(items)
        access_failures = categories["provider"] + categories["secret_store"]
        output[f"{provider}:{connection_id}"] = {
            "provider": provider,
            "connection_id": connection_id,
            "attempts": attempts,
            "models_tested": sorted({item.candidate.model for item in items}),
            "provider_failures": categories["provider"],
            "secret_store_failures": categories["secret_store"],
            "benchmark_internal_failures": categories["benchmark"],
            "availability_rate": round((attempts - access_failures) / attempts, 4) if attempts else 0.0,
            "repeated_failures": repeated,
            "pass_rate": round(sum(1 for item in items if item.ok) / attempts, 4) if attempts else 0.0,
            "mean_score": round(sum(item.score for item in items) / attempts, 2) if attempts else 0.0,
            "mean_latency_ms": round(sum(item.latency_ms for item in items) / attempts, 2) if attempts else 0.0,
            "hard_failures": sum(1 for item in items if item.hard_fail),
        }
    return output


def model_workload_aggregate(results: Sequence[RunResult]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], list[RunResult]] = defaultdict(list)
    for result in results:
        groups[(result.candidate.provider, result.candidate.model, result.task_class)].append(result)
    output: dict[str, Any] = {}
    for (provider, model, task_class), items in sorted(groups.items()):
        summary = _model_group_with_reliability(items)
        output[f"{provider}:{model}:{task_class}"] = summary
    return output


def build_phase_a_payload(
    *,
    inventory: Sequence[Any],
    candidates: Sequence[Any],
    results: Sequence[RunResult],
    created_at: str,
) -> dict[str, Any]:
    return {
        "benchmark_version": 3,
        "phase": "A",
        "decision_mode": "evidence_only",
        "production_registry_mutated": False,
        "routing_policy_mutated": False,
        "allocation_mutated": False,
        "dynamic_onboarding_mutated": False,
        "raw_credentials_returned": False,
        "candidate_inventory": inventory_summary(inventory),
        "candidates": [candidate.__dict__ for candidate in candidates],
        "results": [item.to_dict() for item in results],
        "aggregate": __import__("model_benchmark").aggregate(list(results)),
        "model_level_aggregate": model_level_aggregate(results),
        "model_workload_aggregate": model_workload_aggregate(results),
        "connection_level_aggregate": connection_level_aggregate(results),
        "created_at": created_at,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Registry-driven Phase A benchmark; evidence only, no production routing mutation.")
    parser.add_argument("--repo-root", type=Path, default=BASE_DIR)
    parser.add_argument("--phase-a", action="store_true", help="Discover all locally eligible connections and run the full Phase A shortlist.")
    parser.add_argument("--inventory-only", action="store_true", help="Discover and print candidate inventory without invoking providers.")
    parser.add_argument("--provider", action="append", choices=["openrouter", "groq"], help="Limit auto-discovered providers; repeatable.")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--class", dest="classes", action="append", choices=["SIMPLE", "MEDIUM", "COMPLEX", "LEADER"])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.phase_a and not args.inventory_only:
        parser.error("Use --phase-a for execution or --inventory-only for a dry inventory.")
    if args.repeats < 1:
        parser.error("--repeats must be at least 1")

    root = args.repo_root.resolve()
    store = WindowsProtectedSecretStore()
    providers = tuple(args.provider) if args.provider else ("openrouter", "groq")
    inventory = discover_connection_inventory(secret_store=store)
    candidates = build_phase_a_candidates(inventory, providers=providers)

    inventory_payload = inventory_summary(inventory)
    inventory_payload["benchmark_models"] = {
        "openrouter": list(__import__("model_benchmark").OPENROUTER_CANDIDATES),
        "groq": list(__import__("model_benchmark").GROQ_CANDIDATES),
    }
    inventory_payload["candidate_count"] = len(candidates)
    inventory_payload["candidate_matrix"] = [candidate.__dict__ for candidate in candidates]

    print(json.dumps(inventory_payload, indent=2, ensure_ascii=False))
    if args.inventory_only:
        return 0
    if not args.phase_a:
        return 0
    if not candidates:
        raise SystemExit("No eligible Phase A candidates were discovered from local registry/SecretStore state.")

    started = time.perf_counter()
    results = run_benchmark(
        root,
        candidates,
        args.repeats,
        set(args.classes) if args.classes else None,
    )
    created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    payload = build_phase_a_payload(
        inventory=inventory,
        candidates=candidates,
        results=results,
        created_at=created_at,
    )
    payload["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
    output = args.output.resolve()
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(payload["model_level_aggregate"], indent=2, ensure_ascii=False))
    print(json.dumps(payload["connection_level_aggregate"], indent=2, ensure_ascii=False))
    print(f"Results written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
