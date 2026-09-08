from model_benchmark import (
    Candidate,
    RunResult,
    SCORE_WEIGHTS,
    _contains_secret_like_value,
    _json_object,
    aggregate,
    load_corpus,
)


def test_corpus_has_expected_classes_and_no_production_mutation() -> None:
    corpus = load_corpus()
    classes = {task["class"] for task in corpus["tasks"]}
    assert {"SIMPLE", "MEDIUM", "COMPLEX", "LEADER"}.issubset(classes)
    assert any(task["kind"] == "tool" for task in corpus["tasks"])
    assert corpus["safety"]["production_registry_mutation"] is False
    assert corpus["safety"]["routing_policy_mutation"] is False
    assert corpus["safety"]["raw_credentials_allowed"] is False


def test_candidate_scope_is_explicit() -> None:
    candidate = Candidate("openrouter", "openai/gpt-5.6-luna", "OR-01")
    assert candidate.provider == "openrouter"
    assert candidate.connection_id == "OR-01"


def test_json_envelope_is_deterministic() -> None:
    parsed, ok = _json_object('{"classification":"SIMPLE","objective":"x"}')
    assert ok is True
    assert parsed == {"classification": "SIMPLE", "objective": "x"}

    parsed, ok = _json_object("not json")
    assert parsed is None
    assert ok is False


def test_secret_detection_never_treats_safe_identifiers_as_secrets() -> None:
    assert _contains_secret_like_value("OR-01 fingerprint-present") is False
    assert _contains_secret_like_value("Bearer abc") is True
    assert _contains_secret_like_value("sk-or-v1-example") is True


def test_score_weights_sum_to_100() -> None:
    assert sum(SCORE_WEIGHTS.values()) == 100


def test_aggregate_builds_reliability_score() -> None:
    candidate = Candidate("groq", "openai/gpt-oss-120b", "GROQ-01")
    dimensions = {key: 0.0 for key in SCORE_WEIGHTS}
    result = RunResult(
        candidate,
        "S1",
        "SIMPLE",
        1,
        True,
        95.0,
        dimensions,
        100.0,
        10,
        20,
        0.01,
        True,
        True,
        True,
        True,
        None,
    )
    data = aggregate([result])["openai/gpt-oss-120b::SIMPLE"]
    assert data["success_rate"] == 1.0
    assert data["dimensions"]["reliability"] == 5.0
    assert data["work_product_compatibility_rate"] == 1.0
