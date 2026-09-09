from __future__ import annotations

from pathlib import Path

import pytest
import requests

from central_leader import LeaderRequest
from provider_transport import OpenAICompatibleTransport, ProviderTransportError


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.ok = 200 <= status_code < 300

    def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse | None = None, exception: Exception | None = None) -> None:
        self.response = response
        self.exception = exception
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.exception is not None:
            raise self.exception
        assert self.response is not None
        return self.response


def write_secrets(tmp_path: Path, content: str, monkeypatch: pytest.MonkeyPatch) -> None:
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "openrouter_keys.txt").write_text(content, encoding="utf-8")
    monkeypatch.setenv("AI_AGENT_SECRET_DIR", str(secret_dir))


def leader_request(account_id: str = "OR-03") -> LeaderRequest:
    return LeaderRequest(
        provider="openrouter",
        account_id=account_id,
        model="model-test",
        tier="ULTRA",
        task_id="TASK-1",
        context={"authority": {"execution_authorized": False, "mutation_allowed": False}},
    )


def test_labeled_secret_mapping_uses_stable_connection_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_secrets(tmp_path, "OR-01=key-one\nOR-03=key-three\n", monkeypatch)
    session = FakeSession(
        FakeResponse(
            200,
            {"choices": [{"message": {"content": '{"plan": {"goal": "ok", "tasks": []}}'}}]},
        )
    )

    transport = OpenAICompatibleTransport(session=session)
    transport(leader_request())

    assert session.calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    headers = session.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Bearer key-three"


def test_unlabeled_secrets_are_not_positionally_accepted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_secrets(tmp_path, "key-one\nkey-two\nkey-three\n", monkeypatch)
    transport = OpenAICompatibleTransport(session=FakeSession(FakeResponse(200, {})))

    with pytest.raises(ProviderTransportError, match="stable-ID"):
        transport(leader_request("OR-03"))


def test_http_error_does_not_expose_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "super-secret-key"
    write_secrets(tmp_path, f"OR-01={secret}\n", monkeypatch)
    session = FakeSession(FakeResponse(401, {"error": {"message": secret}}))
    transport = OpenAICompatibleTransport(session=session)

    with pytest.raises(ProviderTransportError) as exc_info:
        transport(leader_request("OR-01"))

    assert secret not in str(exc_info.value)
    assert "401" in str(exc_info.value)
    assert exc_info.value.forensic_evidence is not None
    assert exc_info.value.forensic_evidence["http_status"] == 401
    assert exc_info.value.forensic_evidence["status_category"] == "AUTHENTICATION_FAILURE"
    assert exc_info.value.forensic_evidence["request_classification"] == "openai_compatible_chat_completion"
    assert secret not in str(exc_info.value.forensic_evidence)


@pytest.mark.parametrize(
    ("status_code", "expected_category"),
    [
        (401, "AUTHENTICATION_FAILURE"),
        (403, "AUTHORIZATION_ACCESS_FAILURE"),
        (429, "RATE_LIMIT"),
        (400, "INVALID_REQUEST"),
        (422, "INVALID_REQUEST"),
        (500, "PROVIDER_TRANSIENT_FAILURE"),
        (502, "PROVIDER_TRANSIENT_FAILURE"),
        (503, "PROVIDER_TRANSIENT_FAILURE"),
    ],
)
def test_http_forensic_status_and_category_are_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_category: str,
) -> None:
    write_secrets(tmp_path, "OR-01=test-key\n", monkeypatch)
    session = FakeSession(
        FakeResponse(
            status_code,
            {"error": {"code": "provider-code", "message": "bounded diagnostic"}},
        )
    )
    transport = OpenAICompatibleTransport(session=session)

    with pytest.raises(ProviderTransportError) as exc_info:
        transport.send(
            provider="openrouter",
            account_id="OR-01",
            model="model-test",
            messages=[{"role": "user", "content": "fixture"}],
            task_id="TASK-FORENSIC",
            task_class="SIMPLE",
            repeat=2,
        )

    evidence = exc_info.value.forensic_evidence
    assert evidence is not None
    assert evidence["http_status"] == status_code
    assert evidence["status_category"] == expected_category
    assert evidence["sanitized_error_code"] == "provider-code"
    assert evidence["sanitized_error_message"] == "bounded diagnostic"
    assert evidence["connection_id"] == "OR-01"
    assert evidence["provider"] == "openrouter"
    assert evidence["model"] == "model-test"
    assert evidence["task_id"] == "TASK-FORENSIC"
    assert evidence["task_class"] == "SIMPLE"
    assert evidence["repeat"] == 2
    assert isinstance(evidence["elapsed_ms"], float)


def test_successful_response_shape_and_transport_call_are_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_secrets(tmp_path, "OR-03=key-three\n", monkeypatch)
    session = FakeSession(
        FakeResponse(
            200,
            {"choices": [{"message": {"content": '{"goal": "ok", "tasks": []}'}}]},
        )
    )

    transport = OpenAICompatibleTransport(session=session)
    result = transport(leader_request())

    assert result["plan"] == {"goal": "ok", "tasks": []}
    assert result["provider_response"] == {"status": "OK", "model": "model-test"}
    assert len(session.calls) == 1
    assert session.calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert session.calls[0]["json"] == {
        "model": "model-test",
        "messages": transport._planning_messages(leader_request().context),
        "max_tokens": 500,
        "temperature": 0.0,
    }


def test_connection_error_is_distinguished_without_secret_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "super-secret-key"
    write_secrets(tmp_path, f"OR-01={secret}\n", monkeypatch)
    session = FakeSession(exception=requests.ConnectionError("network unavailable"))
    transport = OpenAICompatibleTransport(session=session)

    with pytest.raises(ProviderTransportError) as exc_info:
        transport(leader_request("OR-01"))

    evidence = exc_info.value.forensic_evidence
    assert evidence is not None
    assert evidence["http_status"] is None
    assert evidence["status_category"] == "NETWORK_OR_TRANSPORT_FAILURE"
    assert evidence["sanitized_error_code"] == "CONNECTION_ERROR"
    assert secret not in str(evidence)


@pytest.mark.parametrize(
    "exception",
    [requests.ConnectTimeout("connect timed out"), requests.Timeout("timed out")],
)
def test_timeout_is_distinguished_without_secret_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
) -> None:
    write_secrets(tmp_path, "OR-01=test-key\n", monkeypatch)
    session = FakeSession(exception=exception)
    transport = OpenAICompatibleTransport(session=session)

    with pytest.raises(ProviderTransportError) as exc_info:
        transport(leader_request("OR-01"))

    evidence = exc_info.value.forensic_evidence
    assert evidence is not None
    assert evidence["http_status"] is None
    assert evidence["status_category"] == "NETWORK_OR_TRANSPORT_FAILURE"
    assert evidence["sanitized_error_code"] in {"CONNECT_TIMEOUT", "REQUEST_TIMEOUT"}


def test_artifact_friendly_evidence_contains_no_credential_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "super-secret-key"
    write_secrets(tmp_path, f"OR-01={secret}\n", monkeypatch)
    session = FakeSession(
        FakeResponse(403, {"error": {"code": "access_denied", "message": f"bad token {secret}"}})
    )
    transport = OpenAICompatibleTransport(session=session)

    with pytest.raises(ProviderTransportError) as exc_info:
        transport.send(
            provider="openrouter",
            account_id="OR-01",
            model="model-test",
            messages=[{"role": "user", "content": "fixture"}],
            task_id="TASK-ARTIFACT",
        )

    evidence = exc_info.value.forensic_evidence
    assert evidence is not None
    assert evidence["status_category"] == "AUTHORIZATION_ACCESS_FAILURE"
    assert "Authorization" not in str(evidence)
    assert secret not in str(evidence)
    assert len(evidence["sanitized_error_message"]) <= 300


def test_malformed_planning_json_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_secrets(tmp_path, "OR-03=key-three\n", monkeypatch)
    session = FakeSession(
        FakeResponse(
            200,
            {"choices": [{"message": {"content": "not-json"}}]},
        )
    )
    transport = OpenAICompatibleTransport(session=session)

    with pytest.raises(ProviderTransportError, match="valid JSON"):
        transport(leader_request())
    assert session.calls[0]["url"] == "https://openrouter.ai/api/v1/chat/completions"
