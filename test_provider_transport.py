from __future__ import annotations

import pytest

from central_leader import LeaderRequest
from provider_transport import OpenAICompatibleTransport, ProviderTransportError
from protected_secret_store import MemorySecretStore
from connection_manager import fingerprint


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


def leader_request(account_id: str = "OR-03") -> LeaderRequest:
    return LeaderRequest(
        provider="openrouter",
        account_id=account_id,
        model="model-test",
        tier="ULTRA",
        task_id="TASK-1",
        context={"authority": {"execution_authorized": False, "mutation_allowed": False}},
    )


def build_store(account_id: str, secret: str) -> MemorySecretStore:
    store = MemorySecretStore()
    store.put(account_id, "openrouter", secret, fingerprint(secret))
    return store


def test_transport_uses_protected_store_by_stable_connection_id() -> None:
    secret = "key-three"
    session = FakeSession(
        FakeResponse(
            200,
            {"choices": [{"message": {"content": '{"plan": {"goal": "ok", "tasks": []}}'}}]},
        )
    )
    transport = OpenAICompatibleTransport(session=session, secret_store=build_store("OR-03", secret))
    transport(leader_request())

    headers = session.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == f"Bearer {secret}"


def test_transport_does_not_fall_back_to_txt_source() -> None:
    session = FakeSession(FakeResponse(200, {}))
    transport = OpenAICompatibleTransport(session=session, secret_store=MemorySecretStore())
    with pytest.raises(ProviderTransportError, match="protected credential"):
        transport(leader_request("OR-03"))


def test_http_error_does_not_expose_secret() -> None:
    secret = "super-secret-key"
    session = FakeSession(FakeResponse(401, {"error": {"message": secret}}))
    transport = OpenAICompatibleTransport(session=session, secret_store=build_store("OR-01", secret))

    with pytest.raises(ProviderTransportError) as exc_info:
        transport(leader_request("OR-01"))
    assert secret not in str(exc_info.value)
    assert "401" in str(exc_info.value)


def test_malformed_planning_json_fails_closed() -> None:
    session = FakeSession(FakeResponse(200, {"choices": [{"message": {"content": "not-json"}}]}))
    transport = OpenAICompatibleTransport(
        session=session,
        secret_store=build_store("OR-03", "key-three"),
    )
    with pytest.raises(ProviderTransportError, match="valid JSON"):
        transport(leader_request())
