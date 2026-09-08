from __future__ import annotations

from pathlib import Path
from typing import Iterable

from connection_manager import fingerprint, load_registry, read_secret_source, save_registry
from protected_secret_store import SecretStore, WindowsProtectedSecretStore

TARGET_IDS = ("GROQ-01", "GROQ-02")


def preview_known_matches(path: Path, *, target_ids: Iterable[str] = TARGET_IDS) -> dict[str, object]:
    """Return a non-secret preview for a possibly unlabeled Groq TXT source."""
    targets = tuple(target_ids)
    registry = load_registry()
    connections = registry.get("connections", {})
    labeled, unlabeled = read_secret_source(path, "GROQ")

    fingerprint_to_id: dict[str, str] = {}
    for connection_id in targets:
        item = connections.get(connection_id)
        if not isinstance(item, dict) or item.get("provider") != "groq":
            continue
        expected = item.get("key_fingerprint")
        if isinstance(expected, str) and expected:
            fingerprint_to_id[expected] = connection_id

    matched: set[str] = set()
    labeled_targets: set[str] = set()
    for connection_id, secret in labeled.items():
        if connection_id in targets and fingerprint(secret) == connections.get(connection_id, {}).get("key_fingerprint"):
            labeled_targets.add(connection_id)
            matched.add(connection_id)

    unmatched_count = 0
    for secret in unlabeled:
        connection_id = fingerprint_to_id.get(fingerprint(secret))
        if connection_id is None:
            unmatched_count += 1
        else:
            matched.add(connection_id)

    return {
        "target_ids": list(targets),
        "matched_ids": sorted(matched),
        "labeled_target_ids": sorted(labeled_targets),
        "labeled_count": len(labeled),
        "unlabeled_count": len(unlabeled),
        "unmatched_count": unmatched_count,
        "all_targets_matched": set(matched) == set(targets),
        "raw_secrets_returned": False,
    }


def import_known_matches(
    path: Path,
    *,
    target_ids: Iterable[str] = TARGET_IDS,
    secret_store: SecretStore | None = None,
) -> dict[str, object]:
    """Store only credentials that cryptographically match existing stable IDs.

    No new connection IDs are created and no provider validation/routing activation is
    performed by this helper.
    """
    targets = tuple(target_ids)
    registry = load_registry()
    connections = registry.get("connections", {})
    store = secret_store or WindowsProtectedSecretStore()
    labeled, unlabeled = read_secret_source(path, "GROQ")

    fingerprint_to_id: dict[str, str] = {}
    for connection_id in targets:
        item = connections.get(connection_id)
        if not isinstance(item, dict) or item.get("provider") != "groq":
            continue
        expected = item.get("key_fingerprint")
        if isinstance(expected, str) and expected:
            fingerprint_to_id[expected] = connection_id

    candidates: dict[str, str] = {}
    rejected = 0
    unmatched = 0
    for connection_id, secret in labeled.items():
        if connection_id not in targets:
            rejected += 1
            continue
        item = connections.get(connection_id)
        if not isinstance(item, dict) or item.get("provider") != "groq":
            rejected += 1
            continue
        if fingerprint(secret) != item.get("key_fingerprint"):
            rejected += 1
            continue
        candidates[connection_id] = secret

    for secret in unlabeled:
        connection_id = fingerprint_to_id.get(fingerprint(secret))
        if connection_id is None:
            unmatched += 1
            continue
        candidates.setdefault(connection_id, secret)

    imported_ids: list[str] = []
    already_present_ids: list[str] = []
    for connection_id, secret in candidates.items():
        item = connections.get(connection_id)
        if not isinstance(item, dict):
            rejected += 1
            continue
        if store.has(connection_id):
            already_present_ids.append(connection_id)
            continue
        fp = fingerprint(secret)
        store.put(connection_id, "groq", secret, fp)
        item["key_fingerprint"] = fp
        item["status"] = "DISABLED"
        item["active"] = False
        item["credential_validated"] = False
        item["validation_required"] = True
        item.pop("failure_reason", None)
        imported_ids.append(connection_id)

    save_registry(registry)
    return {
        "imported_ids": sorted(imported_ids),
        "already_present_ids": sorted(already_present_ids),
        "rejected_count": rejected,
        "unmatched_count": unmatched,
        "stable_ids_created": [],
        "raw_secrets_returned": False,
    }
