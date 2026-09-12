from __future__ import annotations

import os
from typing import Any


def create_default_secret_store() -> Any:
    from protected_secret_store import (
        MemorySecretStore,
        WindowsProtectedSecretStore,
    )

    if os.name == "nt":
        return WindowsProtectedSecretStore()

    return MemorySecretStore()
