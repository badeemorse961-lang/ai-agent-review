from __future__ import annotations

import json
from pathlib import Path

from connection_manager import fingerprint
from model_benchmark import Candidate, RunResult
from phase_a_candidate_inventory import build_phase_a_candidates, discover_connection_inventory
from tools.run_phase_a_benchmark import connection_level_aggregate, model_level_aggregate


class FakeSecretStore:
    def __init__(self, values: dict[tuple[str, str], str]) -> None:
        self.values = values

    def has(self, connection_id: str) -> bool:
        return any(key[0] == connection_id for key in self.values)

    def get(self, connection_id: str, provider: str) -> str:
        return self.values[(connection_id, provider)]


def _write_fixture(tmp_path: Path) -> tuple[Path, Path, dict[tuple[str, str], str]]:
    registry_path = tmp_path / "registry.json"
    metadata_path = tmp_path / "connections.json"
    authoritative = {
        "architecture": {
            "leader": {
                "primary_model": "nvidia/nemotron-3-ultra-550b-a55b:free",
                "failover_model": "nvidia/nemotron-3-super-120b-a12b:free",
                "primary_pool": ["OR-01"],
                "failover_pool": ["OR-01"],
            },
            "workers": {
                "model": "openai/gpt-oss-120b",
                "roles": {"coder": ["GROQ-01"], "reviewer": ["GROQ-02"]},
            },
        }
    }
    secrets = {
        ("OR-01", "openrouter"): "or-secret",
        ("GROQ-01", "groq"): "groq-secret-1",
        ("GROQ-02", "groq"): "groq-secret-2",
    }
    metadata = {"version": 2, "connections": {}}
    for (connection_id, provider), secret in secrets.items():
        metadata["connections"][connection_id] = {
            "connection_id": connection_id,
            "provider": provider,
            "key_fingerprint": fingerprint(secret),
            "status": "VALIDATED",
        }
    registry_path.write_text(json.dumps(authoritative), encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return registry_path, metadata_path, secrets


def _result(candidate: Candidate, *, ok: bool, score: float, error: str | None = None) -> RunResult:
    dimensions = {"correctness": score, "solution_quality": 0.0, "reasoning": 0.0, "instruction_adherence": 0.0, "tool_structured": 0.0, "regression_safety": 0.0, "latency": 0.0, "reliability": 5.0 if ok else 0.0}
    return RunResult(
        candidate=candidate,
        task_id="S1",
        task_class="SIMPLE",
        repeat=1,
        ok=ok,
        semantic_pass=ok,
        hard_fail=not ok,
        hard_failure_codes=("provider_failure",) if error == "HTTPError" else (),
        score=score,
        dimensions=dimensions,
        latency_ms=100.0,
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.1,
        structured_ok=ok,
        tool_ok=True,
        regression_ok=True,
        work_product_compatible=True,
        reliability_score=5.0 if ok else 0.0,
        error=error,
    )


def test_inventory_uses_registry_roles_and_configured_models(tmp_path: Path) -> None:
    registry_path, metadata_path, secrets = _write_fixture(tmp_path)
    inventory = discover_connection_inventory(
        authoritative_registry_path=registry_path,
        connection_metadata_path=metadata_path,
        secret_store=FakeSecretStore(secrets),
    )
    rows = {item.connection_id: item for item in inventory}
    assert rows["GROQ-01"].configured_models == ("openai/gpt-oss-120b",)
    assert rows["GROQ-01"].capability_roles == ("Worker:coder",)
    assert rows["GROQ-01"].ready is True
    assert rows["OR-01"].configured_models == (
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
    )
    assert rows["OR-01"].capability_roles == ("Leader:Primary", "Leader:Failover")


def test_candidate_matrix_uses_only_registry_configured_shortlisted_models(tmp_path: Path) -> None:
    registry_path, metadata_path, secrets = _write_fixture(tmp_path)
    inventory = discover_connection_inventory(
        authoritative_registry_path=registry_path,
        connection_metadata_path=metadata_path,
        secret_store=FakeSecretStore(secrets),
    )
    groq = build_phase_a_candidates(inventory, providers=("groq",))
    assert {item.model for item in groq} == {"openai/gpt-oss-120b"}
    assert {item.connection_id for item in groq} == {"GROQ-01", "GROQ-02"}
    assert len(groq) == 2


def test_model_aggregate_macro_averages_connections() -> None:
    model = "openai/gpt-oss-120b"
    results = [
        _result(Candidate("groq", model, "GROQ-01"), ok=True, score=30.0),
        _result(Candidate("groq", model, "GROQ-02"), ok=False, score=0.0, error="HTTPError"),
    ]
    aggregate = model_level_aggregate(results)["groq:openai/gpt-oss-120b"]
    assert aggregate["connections_tested"] == 2
    assert aggregate["pass_rate"] == 0.5
    assert aggregate["mean_score"] == 15.0
    assert aggregate["reliability"] == 2.5


def test_connection_aggregate_counts_provider_and_secretstore_failures() -> None:
    model = "openai/gpt-oss-120b"
    results = [
        _result(Candidate("groq", model, "GROQ-01"), ok=False, score=0.0, error="HTTPError"),
        _result(Candidate("groq", model, "GROQ-01"), ok=False, score=0.0, error="SecretStoreError"),
        _result(Candidate("groq", model, "GROQ-01"), ok=False, score=0.0, error="HTTPError"),
    ]
    aggregate = connection_level_aggregate(results)["groq:GROQ-01"]
    assert aggregate["provider_failures"] == 2
    assert aggregate["secret_store_failures"] == 1
    assert aggregate["availability_rate"] == 0.0
    assert aggregate["repeated_failures"] == 1
