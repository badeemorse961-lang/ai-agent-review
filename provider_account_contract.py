from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Any, Optional, Iterable

def _require_string_sequence(value, field: str) -> tuple[str, ...]:
    if value is None:
        raise ValueError(f"ProviderAccount {field} must be a sequence")
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"ProviderAccount {field} must be a sequence of strings, got {type(value).__name__}")
    normalized = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"ProviderAccount {field} contains non-string: {type(item).__name__}")
        stripped = item.strip()
        if not stripped:
            raise ValueError(f"ProviderAccount {field} contains empty string")
        normalized.append(stripped)
    return tuple(dict.fromkeys(normalized))

def _require_optional_string(value, field: str) -> Optional[str]:
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
    fingerprint: str  # fingerprint only; never secret value
    status: str      # e.g., VALIDATED, KEY_ROTATED, NOT_PRESENT_IN_SECRET_SOURCE, ACTIVE, INACTIVE
    active: bool
    capabilities: tuple[str, ...] = ()
    role: str | None = None
    # Note: no secret fields; no raw key; no bearer token; adapter over existing connection_manager authority

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
        # Security: reject secret-bearing fingerprint patterns
        if fp.startswith("sk-") or fp.startswith("Bearer ") or "secret_value" in fp:
            raise ValueError("fingerprint appears to contain secret material")
        status = d.get("status")
        if not isinstance(status, str) or not status.strip():
            raise ValueError("status must be non-empty string")
        active = d.get("active")
        if not isinstance(active, bool):
            raise ValueError("active must be bool")
        # Strict validation - no coercion
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
    # Adapter over existing connection_manager / credential_pool_manager / provider_transport
    # Not a replacement registry; uses existing authorities
    def __init__(self):
        pass

    def _load_active_pool(self) -> dict:
        """Load active pool from credential_pool_manager if available."""
        try:
            from credential_pool_manager import get_active_pool
            return get_active_pool()
        except ImportError:
            return {}
        except Exception:
            return {}

    def _load_registry(self) -> dict:
        """Load registry from connection_manager."""
        try:
            from connection_manager import load_registry
            return load_registry()
        except ImportError:
            return {}
        except Exception:
            return {}

    def resolve_account(
        self,
        connection_id: str,
        provider_hint: str | None = None,
    ) -> ProviderAccount:
        # Check active pool first (authoritative for current credential state)
        active_pool = self._load_active_pool()
        active_item = active_pool.get(connection_id)
        
        # Also check registry for metadata
        registry = self._load_registry()
        registry_item = registry.get("connections", {}).get(connection_id)
        
        # Merge: active pool is authoritative for active status; registry for other metadata
        if active_item is not None:
            # Active pool has the account - use it as primary source
            provider = active_item.get("provider", provider_hint)
            if not provider:
                raise ValueError(f"Active pool account {connection_id} has no provider")
            fingerprint = active_item.get("key_fingerprint", "unknown")
            status = active_item.get("status", "UNKNOWN")
            active = active_item.get("active", False)
            capabilities = active_item.get("capabilities", ())
            role = active_item.get("role")
        elif registry_item is not None:
            # Fall back to registry for metadata
            provider = registry_item.get("provider", provider_hint)
            if not provider:
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
            "provider": str(provider).strip(),
            "fingerprint": fingerprint,
            "status": status,
            "active": active,
            "capabilities": capabilities,
            "role": role,
        })

    def list_accounts_for_provider(self, provider: str) -> list[ProviderAccount]:
        # Merge active pool and registry
        active_pool = self._load_active_pool()
        registry = self._load_registry()
        
        # Get all unique connection IDs from both sources
        all_connection_ids = set()
        for cid, item in active_pool.items():
            if isinstance(item, dict) and str(item.get("provider", "")).strip() == provider.strip():
                all_connection_ids.add(cid)
        for cid, item in registry.get("connections", {}).items():
            if isinstance(item, dict) and str(item.get("provider", "")).strip() == provider.strip():
                all_connection_ids.add(cid)
        
        result = []
        for cid in sorted(all_connection_ids):
            try:
                acc = self.resolve_account(cid, provider)
                result.append(acc)
            except ValueError:
                pass
        return result
