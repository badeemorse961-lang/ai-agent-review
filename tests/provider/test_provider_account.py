import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/projects")

import connection_manager
import credential_pool_manager
import provider_transport
from provider_account_contract import ProviderAccount, ProviderAccountService


def _base_account(**overrides):
    value = {
        "connection_id": "OR-01",
        "provider": "openrouter",
        "fingerprint": "sha256:ok",
        "status": "VALIDATED",
        "active": True,
        "capabilities": [],
        "role": None,
    }
    value.update(overrides)
    return value


def test_provider_account_strict_validation():
    for field, bad_value, marker in (
        ("capabilities", ["chat", 123], "non-string"),
        ("capabilities", [""], "empty"),
        ("capabilities", "chat", "sequence"),
        ("role", 123, "role"),
        ("role", "", "non-empty"),
        ("provider", 123, "provider"),
        ("active", "true", "active"),
    ):
        try:
            ProviderAccount.from_dict(_base_account(**{field: bad_value}))
        except ValueError as exc:
            assert marker in str(exc)
        else:
            raise AssertionError(f"should reject invalid {field}={bad_value!r}")


def test_existing_and_rebound_accounts_and_transport_lookup():
    service = ProviderAccountService()
    original_pool = credential_pool_manager.get_active_pool()
    original_registry_file = connection_manager.REGISTRY_FILE
    original_secret_dir = connection_manager.secret_dir
    original_transport_resolve = provider_transport.resolve_secret_file

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        secret_dir = root / "secrets"
        secret_dir.mkdir()
        secret_file = secret_dir / "openrouter_keys.txt"
        secret_file.write_text(
            "OR-01=sk-or-key-1\nOR-02=sk-or-key-2\n",
            encoding="utf-8",
        )

        connection_manager.REGISTRY_FILE = root / "connections.json"
        connection_manager.REGISTRY_FILE.write_text(
            '{"version": 2, "connections": {}}',
            encoding="utf-8",
        )
        connection_manager.secret_dir = lambda: secret_dir

        try:
            registry = connection_manager.load_registry()
            connection_manager.import_provider(
                provider="openrouter",
                keys_path=secret_file,
                registry=registry,
                prefix="OR",
            )
            connection_manager.save_registry(registry)

            result = credential_pool_manager.reload_credential_pool(
                provider="openrouter",
                prefix="OR",
            )
            assert result["status"] == "success"
            pool = credential_pool_manager.get_active_pool()
            assert "OR-01" in pool
            assert "OR-02" in pool

            rebound = service.resolve_account("OR-02")
            assert rebound.connection_id == "OR-02"
            assert rebound.provider == "openrouter"
            assert rebound.fingerprint == pool["OR-02"]["key_fingerprint"]
            assert rebound.status == pool["OR-02"]["status"]

            existing = service.resolve_account("OR-01", provider_hint="openrouter")
            assert existing.connection_id == "OR-01"
            assert existing.provider == "openrouter"

            provider_transport.resolve_secret_file = lambda provider: secret_file
            resolved = provider_transport.OpenAICompatibleTransport._resolve_key(
                "openrouter", "OR", "OR-02"
            )
            assert resolved == "sk-or-key-2"
        finally:
            with credential_pool_manager._pool_lock:
                credential_pool_manager._active_pool.clear()
                credential_pool_manager._active_pool.update(original_pool)
            connection_manager.REGISTRY_FILE = original_registry_file
            connection_manager.secret_dir = original_secret_dir
            provider_transport.resolve_secret_file = original_transport_resolve


def test_secret_safety():
    account = ProviderAccount(
        connection_id="OR-01",
        provider="openrouter",
        fingerprint="sha256:abcd1234",
        status="VALIDATED",
        active=True,
        capabilities=("chat", "completion"),
        role="coder",
    )
    data = account.to_dict()
    assert "key" not in data
    assert "secret" not in data
    assert "token" not in data
    assert "password" not in data
    assert "sk-" not in data["fingerprint"]
    assert not data["fingerprint"].startswith("Bearer ")


def test_unknown_account():
    service = ProviderAccountService()
    try:
        service.resolve_account("XX-99")
    except ValueError as exc:
        assert "unknown" in str(exc).lower()
    else:
        raise AssertionError("should reject unknown connection")


def test_authority_preservation():
    content = Path("/projects/provider_account_contract.py").read_text(encoding="utf-8")
    assert "class IndependentValidator" not in content
    assert "class ExecutionAuthorizationBoundary" not in content
    assert "class ExecutionGate" not in content
    assert "class GitMutationExecutor" not in content
    assert "class WorkerWorkProduct" not in content
    assert "class connection_manager" not in content
    assert "class credential_pool_manager" not in content
    assert "get_active_pool" in content
    assert "load_registry" in content


if __name__ == "__main__":
    test_provider_account_strict_validation()
    test_existing_and_rebound_accounts_and_transport_lookup()
    test_secret_safety()
    test_unknown_account()
    test_authority_preservation()
    print("ALL PROVIDER ACCOUNT CORRECTED TESTS PASS")
