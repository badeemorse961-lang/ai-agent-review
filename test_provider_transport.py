from __future__ import annotations

from pathlib import Path

import pytest

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
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
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
