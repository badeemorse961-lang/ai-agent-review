from __future__ import annotations

import ctypes
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path
from typing import Any, Protocol


STORE_ENV = "AI_AGENT_PROTECTED_SECRET_STORE"
DEFAULT_STORE_PATH = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local"))
    / "AI-Agent"
    / "protected-secrets.bin"
)


class SecretStoreError(RuntimeError):
    """Raised when protected secret storage cannot be used safely."""


class SecretStore(Protocol):
    def put(self, connection_id: str, provider: str, secret: str, fingerprint: str) -> None: ...
    def get(self, connection_id: str, provider: str | None = None) -> str: ...
    def delete(self, connection_id: str) -> bool: ...
    def has(self, connection_id: str) -> bool: ...
    def list_ids(self) -> list[str]: ...


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _DpapiBackend:
    def __init__(self) -> None:
        if os.name != "nt":
            raise SecretStoreError("Windows DPAPI protected storage is only available on Windows")
        try:
            self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        except OSError as exc:
            raise SecretStoreError("Windows CryptProtectData is unavailable") from exc
        self._crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DATA_BLOB),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DATA_BLOB),
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DATA_BLOB),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DATA_BLOB),
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(_DATA_BLOB),
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self._kernel32.LocalFree.restype = wintypes.HLOCAL

    @staticmethod
    def _blob(data: bytes) -> tuple[_DATA_BLOB, Any]:
        buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        return _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

    def protect(self, plaintext: bytes) -> bytes:
        input_blob, _ = self._blob(plaintext)
        output_blob = _DATA_BLOB()
        flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
        if not self._crypt32.CryptProtectData(
            ctypes.byref(input_blob),
            "AI-Agent Protected Secret Store",
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        ):
            error = ctypes.get_last_error()
            raise SecretStoreError(f"CryptProtectData failed with Win32 error {error}")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self._kernel32.LocalFree(output_blob.pbData)

    def unprotect(self, ciphertext: bytes) -> bytes:
        input_blob, _ = self._blob(ciphertext)
        output_blob = _DATA_BLOB()
        description = wintypes.LPWSTR()
        flags = 0x1
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),
            ctypes.byref(description),
            None,
            None,
            None,
            flags,
            ctypes.byref(output_blob),
        ):
            error = ctypes.get_last_error()
            raise SecretStoreError(f"CryptUnprotectData failed with Win32 error {error}")
        try:
            return ctypes.string_at(output_blob.pbData, output_blob.cbData)
        finally:
            self._kernel32.LocalFree(output_blob.pbData)
            if description:
                self._kernel32.LocalFree(description)


class WindowsProtectedSecretStore:
    """User-scoped Windows DPAPI store; the on-disk file is encrypted ciphertext."""

    def __init__(self, path: Path | None = None, backend: Any | None = None) -> None:
        self.path = Path(path) if path else Path(os.environ.get(STORE_ENV, DEFAULT_STORE_PATH))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._backend = backend or _DpapiBackend()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "connections": {}}
        try:
            encrypted = self.path.read_bytes()
            plaintext = self._backend.unprotect(encrypted)
            data = json.loads(plaintext.decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecretStoreError("Protected secret store cannot be read") from exc
        if not isinstance(data, dict) or not isinstance(data.get("connections"), dict):
            raise SecretStoreError("Protected secret store has invalid structure")
        return data

    def _save(self, data: dict[str, Any]) -> None:
        plaintext = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        encrypted = self._backend.protect(plaintext)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass

    def put(self, connection_id: str, provider: str, secret: str, fingerprint: str) -> None:
        if not connection_id or not provider or not isinstance(secret, str) or not secret:
            raise SecretStoreError("Protected secret record is invalid")
        if not fingerprint or len(fingerprint) != 64:
            raise SecretStoreError("Protected secret fingerprint is invalid")
        data = self._load()
        data["connections"][connection_id] = {
            "provider": provider,
            "fingerprint": fingerprint,
            "secret": secret,
        }
        self._save(data)

    def get(self, connection_id: str, provider: str | None = None) -> str:
        data = self._load()
        item = data["connections"].get(connection_id)
        if not isinstance(item, dict):
            raise SecretStoreError(f"No protected secret exists for {connection_id}")
        if provider is not None and item.get("provider") != provider:
            raise SecretStoreError("Protected secret provider does not match connection")
        secret = item.get("secret")
        if not isinstance(secret, str) or not secret:
            raise SecretStoreError("Protected secret record is invalid")
        return secret

    def delete(self, connection_id: str) -> bool:
        data = self._load()
        if connection_id not in data["connections"]:
            return False
        del data["connections"][connection_id]
        self._save(data)
        return True

    def has(self, connection_id: str) -> bool:
        data = self._load()
        return connection_id in data["connections"]

    def list_ids(self) -> list[str]:
        return sorted(str(item) for item in self._load()["connections"])


class MemorySecretStore:
    """Deterministic test double; never used by the production Windows entry point."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, str]] = {}

    def put(self, connection_id: str, provider: str, secret: str, fingerprint: str) -> None:
        self.records[connection_id] = {
            "provider": provider,
            "secret": secret,
            "fingerprint": fingerprint,
        }

    def get(self, connection_id: str, provider: str | None = None) -> str:
        item = self.records[connection_id]
        if provider is not None and item["provider"] != provider:
            raise SecretStoreError("Protected secret provider does not match connection")
        return item["secret"]

    def delete(self, connection_id: str) -> bool:
        return self.records.pop(connection_id, None) is not None

    def has(self, connection_id: str) -> bool:
        return connection_id in self.records

    def list_ids(self) -> list[str]:
        return sorted(self.records)
