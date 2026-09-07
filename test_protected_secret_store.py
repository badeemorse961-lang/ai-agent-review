from __future__ import annotations

import os
from pathlib import Path

import pytest

from protected_secret_store import SecretStoreError, WindowsProtectedSecretStore


class FakeCipher:
    def protect(self, plaintext: bytes) -> bytes:
        return b"PROTECTED:" + plaintext[::-1]

    def unprotect(self, ciphertext: bytes) -> bytes:
        assert ciphertext.startswith(b"PROTECTED:")
        return ciphertext[len(b"PROTECTED:"):][::-1]


def test_store_persists_without_raw_secret_on_disk(tmp_path: Path) -> None:
    secret = "super-secret-value"
    path = tmp_path / "protected.bin"
    store = WindowsProtectedSecretStore(path=path, backend=FakeCipher())
    store.put("GROQ-01", "groq", secret, "a" * 64)

    assert secret.encode("utf-8") not in path.read_bytes()

    restarted = WindowsProtectedSecretStore(path=path, backend=FakeCipher())
    assert restarted.get("GROQ-01", "groq") == secret
    assert restarted.has("GROQ-01")


def test_real_backend_requires_windows() -> None:
    if os.name == "nt":
        store = WindowsProtectedSecretStore()
        assert store is not None
    else:
        with pytest.raises(SecretStoreError, match="Windows DPAPI"):
            WindowsProtectedSecretStore()
