from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from application_boundary import ApplicationIntent, ApplicationResult
from connection_manager import (
    PROVIDER_PREFIXES,
    fingerprint,
    load_registry,
    read_secret_source,
    save_registry,
)
from protected_secret_store import SecretStoreError


GROQ_STABLE_IMPORT_IDS = tuple(f"GROQ-{number:02d}" for number in range(1, 16))


def _known_groq_ids(registry: Mapping[str, Any]) -> tuple[str, ...]:
    connections = registry.get("connections", {})
    if not isinstance(connections, Mapping):
        return GROQ_STABLE_IMPORT_IDS
    return tuple(
        connection_id
        for connection_id in GROQ_STABLE_IMPORT_IDS
        if isinstance(connections.get(connection_id), Mapping)
        and connections[connection_id].get("provider") == "groq"
        and connections[connection_id].get("status") != "REMOVED"
    )


def _preview(app: Any, source: Path) -> None:
    from tkinter import messagebox

    try:
        labeled, unlabeled = read_secret_source(source, PROVIDER_PREFIXES["groq"])
    except Exception as exc:
        messagebox.showerror("Groq import", f"Cannot read TXT source: {type(exc).__name__}: {exc}")
        return

    registry = load_registry()
    connections = registry.get("connections", {})
    known_ids = _known_groq_ids(registry)
    known_by_fingerprint = {
        str(item.get("key_fingerprint")): connection_id
        for connection_id in known_ids
        if isinstance((item := connections.get(connection_id)), Mapping)
        and isinstance(item.get("key_fingerprint"), str)
        and item.get("key_fingerprint")
    }

    matches: list[str] = []
    for secret in unlabeled:
        connection_id = known_by_fingerprint.get(fingerprint(secret))
        if connection_id and connection_id not in matches:
            matches.append(connection_id)

    labeled_targets = sorted(set(labeled) & set(known_ids))
    unexpected_ids = sorted(set(labeled) - set(known_ids))
    all_matches = sorted(set(matches) | set(labeled_targets))
    unmatched = max(0, len(unlabeled) - len(matches))
    summary = [
        "SAFE GROQ IMPORT PREVIEW",
        "",
        f"Source: {source}",
        f"Total source entries: {len(labeled) + len(unlabeled)}",
        f"Existing stable Groq IDs: {len(known_ids)}",
        f"Known matches: {len(all_matches)}",
        f"Matched IDs: {', '.join(all_matches) if all_matches else '(none)'}",
        f"Unlabeled entries: {len(unlabeled)}",
        f"Unmatched entries: {unmatched}",
        f"Unexpected explicit IDs: {', '.join(unexpected_ids) if unexpected_ids else '(none)'}",
        "",
        "Credential values are never displayed.",
        "Only existing GROQ-01 through GROQ-15 identities can be imported.",
        "No new Groq connection IDs will be created by this flow.",
    ]
    if not all_matches or unexpected_ids:
        messagebox.showwarning("Groq import blocked", "\n".join(summary) + "\n\nNo complete stable import set was identified.")
        return
    if not messagebox.askyesno("Confirm Groq import", "\n".join(summary) + "\n\nImport matched existing credentials into protected storage?"):
        return

    result = _import_existing(app, source)
    app.show("Connections & Pools")
    app._set_status(result)


def _import_existing(app: Any, source: Path) -> ApplicationResult:
    try:
        labeled, unlabeled = read_secret_source(source, PROVIDER_PREFIXES["groq"])
        registry = load_registry()
        connections = registry.get("connections", {})
        stable_ids = _known_groq_ids(registry)
        by_fingerprint = {
            str(item.get("key_fingerprint")): connection_id
            for connection_id in stable_ids
            if isinstance((item := connections.get(connection_id)), Mapping)
            and isinstance(item.get("key_fingerprint"), str)
            and item.get("key_fingerprint")
        }
        assignments: dict[str, str] = dict(labeled)
        for secret in unlabeled:
            connection_id = by_fingerprint.get(fingerprint(secret))
            if connection_id is not None:
                if connection_id in assignments and assignments[connection_id] != secret:
                    return ApplicationResult("REJECTED", {}, f"Multiple credentials matched {connection_id}")
                assignments[connection_id] = secret

        missing = [connection_id for connection_id in stable_ids if connection_id not in assignments]
        if missing:
            return ApplicationResult(
                "REJECTED",
                {"provider": "groq", "connection_ids": sorted(assignments)},
                f"Stable Groq import set incomplete; missing {len(missing)} known credentials",
            )

        store = app.service.secret_store
        imported = 0
        already_present = 0
        for connection_id, secret in assignments.items():
            if connection_id not in stable_ids:
                return ApplicationResult("REJECTED", {}, f"Unexpected Groq connection ID: {connection_id}")
            item = connections.get(connection_id)
            if not isinstance(item, dict) or item.get("provider") != "groq":
                return ApplicationResult("REJECTED", {}, f"Groq connection metadata missing: {connection_id}")
            fp = fingerprint(secret)
            if item.get("key_fingerprint") != fp:
                return ApplicationResult("REJECTED", {}, f"Credential fingerprint mismatch for {connection_id}")
            try:
                present = store.has(connection_id)
            except Exception:
                present = False
            if present:
                already_present += 1
                continue
            store.put(connection_id, "groq", secret, fp)
            imported += 1

        save_registry(registry)
        return ApplicationResult(
            "OK" if imported or already_present else "NO_CHANGES",
            {
                "provider": "groq",
                "imported_count": imported,
                "already_present_count": already_present,
                "rejected_count": 0,
                "persistence_status": "PERSISTED",
                "connection_ids": sorted(assignments),
                "raw_secrets_returned": False,
                "new_connection_ids_created": False,
            },
        )
    except SecretStoreError as exc:
        return ApplicationResult("ERROR", {}, f"SecretStoreError: {exc}"[:240])
    except Exception as exc:
        return ApplicationResult("ERROR", {}, f"{type(exc).__name__}: {exc}"[:240])


def _verify(app: Any) -> None:
    from tkinter import messagebox

    registry = load_registry()
    connections = registry.get("connections", {})
    results: list[dict[str, str]] = []
    all_ready = True
    for connection_id in GROQ_STABLE_IMPORT_IDS:
        item = connections.get(connection_id)
        if not isinstance(item, Mapping) or item.get("provider") != "groq":
            results.append({"connection_id": connection_id, "state": "NOT_READY", "reason": "CONNECTION_ID_MISMATCH"})
            all_ready = False
            continue
        expected = item.get("key_fingerprint")
        if not isinstance(expected, str) or not expected:
            results.append({"connection_id": connection_id, "state": "NOT_READY", "reason": "FINGERPRINT_MISSING"})
            all_ready = False
            continue
        try:
            secret = app.service.secret_store.get(connection_id, "groq")
        except SecretStoreError:
            results.append({"connection_id": connection_id, "state": "NOT_READY", "reason": "SECRET_RECORD_MISSING"})
            all_ready = False
            continue
        if fingerprint(secret) != expected:
            results.append({"connection_id": connection_id, "state": "NOT_READY", "reason": "FINGERPRINT_MISMATCH"})
            all_ready = False
            continue
        results.append({"connection_id": connection_id, "state": "READY", "reason": "PROTECTED_CREDENTIAL_RETRIEVABLE"})

    lines = ["GROQ PROTECTED-CREDENTIAL READINESS", ""]
    lines.extend(f"{item['connection_id']} = {item['state']} — {item['reason']}" for item in results)
    lines.extend(["", "Credential values displayed: NO", "Routing mutated: NO", "Activation mutated: NO"])
    if all_ready:
        messagebox.showinfo("Groq readiness", "\n".join(lines))
    else:
        messagebox.showwarning("Groq readiness", "\n".join(lines))
    app._set_status(ApplicationResult("OK" if all_ready else "FAILED", {"connections": results}), "Groq protected-credential readiness checked")


def install_full_groq_import(app_class: type) -> None:
    def preview(self: Any, source: Path) -> None:
        _preview(self, source)

    def verify(self: Any) -> None:
        _verify(self)

    app_class._groq_import_preview = preview
    app_class._verify_groq_readiness = verify
