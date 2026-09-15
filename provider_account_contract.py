from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


def _require_string_sequence(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        raise ValueError(f"ProviderAccount {field} must be a sequence")
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"ProviderAccount {field} must be a sequence of strings, got {type(value).__name__}")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"ProviderAccount {field} contains non-string: {type(item).__name__}")
        stripped = item.strip()
        if not stripped:
            raise ValueError(f"ProviderAccount {field} contains empty string")
        normalized.append(stripped)
    return tuple(dict.fromkeys(normalized))


def _require_optional_string(value: Any, field: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"ProviderAccount {field} must be a string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"ProviderAccount {field} must be non-empty string if provided")
    return stripped


@dataclass(frozen=True)
class ProviderAccount:
    connection_id: str
    provider: str
    fingerprint: str
    status: str
    active: bool
    capabilities: tuple[str, ...] = ()
    role: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "provider": self.provider,
            "fingerprint": self.fingerprint,
            "status": self.status,
            "active": self.active,
            "capabilities": list(self.capabilities),
            "role": self.role,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProviderAccount":
        if not isinstance(d, dict):
            raise ValueError("ProviderAccount requires dict input")
        cid = d.get("connection_id")
        if not isinstance(cid, str) or not cid.strip():
            raise ValueError("connection_id must be non-empty string")
        provider = d.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be non-empty string")
        fp = d.get("fingerprint")
        if not isinstance(fp, str) or not fp.strip():
            raise ValueError("fingerprint must be non-empty string")
        if fp.startswith("sk-") or fp.startswith("Bearer ") or "secret_value" in fp:
            raise ValueError("fingerprint appears to contain secret material")
        status = d.get("status")
        if not isinstance(status, str) or not status.strip():
            raise ValueError("status must be non-empty string")
        active = d.get("active")
        if not isinstance(active, bool):
            raise ValueError("active must be bool")
        capabilities = _require_string_sequence(d.get("capabilities"), "capabilities")
        role = _require_optional_string(d.get("role"), "role")
        return cls(
            connection_id=cid.strip(),
            provider=provider.strip(),
            fingerprint=fp.strip(),
            status=status.strip(),
            active=active,
            capabilities=capabilities,
            role=role,
        )


class ProviderAccountService:
    """Read adapter over existing connection and credential authorities."""

    def _load_active_pool(self) -> dict:
        try:
            from credential_pool_manager import get_active_pool

            return get_active_pool()
        except Exception:
            return {}

    def _load_registry(self) -> dict:
        try:
            from connection_manager import load_registry

            return load_registry()
        except Exception:
            return {}

    def resolve_account(
        self,
        connection_id: str,
        provider_hint: str | None = None,
    ) -> ProviderAccount:
        if not isinstance(connection_id, str) or not connection_id.strip():
            raise ValueError("connection_id must be non-empty string")
        if provider_hint is not None and (
            not isinstance(provider_hint, str) or not provider_hint.strip()
        ):
            raise ValueError("provider_hint must be non-empty string if provided")

        active_pool = self._load_active_pool()
        active_item = active_pool.get(connection_id)
        registry_connections = self._load_registry().get("connections", {})
        registry_item = registry_connections.get(connection_id)

        if active_item is not None:
            provider = active_item.get("provider")
            if provider is None and isinstance(registry_item, dict):
                provider = registry_item.get("provider")
            if provider is None:
                provider = provider_hint
            if not isinstance(provider, str) or not provider.strip():
                raise ValueError(f"Active pool account {connection_id} has no provider metadata")
            fingerprint = active_item.get("key_fingerprint", "unknown")
            status = active_item.get("status", "UNKNOWN")
            active = active_item.get("active", False)
            capabilities = active_item.get("capabilities", ())
            role = active_item.get("role")
        elif isinstance(registry_item, dict):
            provider = registry_item.get("provider")
            if provider is None:
                provider = provider_hint
            if not isinstance(provider, str) or not provider.strip():
                raise ValueError(f"Registry account {connection_id} has no provider")
            fingerprint = registry_item.get("key_fingerprint", "unknown")
            status = registry_item.get("status", "UNKNOWN")
            active = registry_item.get("active", False)
            capabilities = registry_item.get("capabilities", ())
            role = registry_item.get("role")
        else:
            raise ValueError(f"Unknown connection: {connection_id}")

        return ProviderAccount.from_dict({
            "connection_id": connection_id,
            "provider": provider,
            "fingerprint": fingerprint,
            "status": status,
            "active": active,
            "capabilities": capabilities,
            "role": role,
        })

    def list_accounts_for_provider(self, provider: str) -> list[ProviderAccount]:
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("provider must be non-empty string")
        provider = provider.strip()
        active_pool = self._load_active_pool()
        registry_connections = self._load_registry().get("connections", {})

        all_connection_ids: set[str] = set()
        for cid, item in active_pool.items():
            if isinstance(item, dict) and item.get("provider") == provider:
                all_connection_ids.add(cid)
        for cid, item in registry_connections.items():
            if isinstance(item, dict) and item.get("provider") == provider:
                all_connection_ids.add(cid)

        result: list[ProviderAccount] = []
        for cid in sorted(all_connection_ids):
            try:
                result.append(self.resolve_account(cid, provider))
            except ValueError:
                continue
        return result
