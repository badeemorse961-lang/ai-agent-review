from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from connection_manager import (
    PROVIDER_PREFIXES,
    _legacy_secret_file,
    import_provider,
    load_registry,
    resolve_secret_file,
    save_registry,
    secret_file,
)


class ConnectionManagerTests(unittest.TestCase):
    def test_external_secret_directory_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            external = root / "external"
            external.mkdir()
            (external / "groq_keys.txt").write_text("secret-a\n", encoding="utf-8")

            with patch.dict(os.environ, {"AI_AGENT_SECRET_DIR": str(external)}, clear=False):
                resolved = resolve_secret_file("groq")

            self.assertEqual(resolved, external / "groq_keys.txt")

    def test_legacy_repo_secret_requires_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            legacy = root / "groq_keys.txt"
            with patch("connection_manager.BASE_DIR", root):
                legacy.write_text("secret-a\n", encoding="utf-8")
                with patch.dict(
                    os.environ,
                    {"AI_AGENT_SECRET_DIR": str(root / "missing")},
                    clear=False,
                ):
                    os.environ.pop("AI_AGENT_ALLOW_LEGACY_SECRET_PATH", None)
                    with self.assertRaises(FileNotFoundError):
                        resolve_secret_file("groq")

                    with patch.dict(
                        os.environ,
                        {"AI_AGENT_ALLOW_LEGACY_SECRET_PATH": "1"},
                        clear=False,
                    ):
                        self.assertEqual(resolve_secret_file("groq"), legacy)

    def test_unlabeled_keys_preserve_existing_ids_by_fingerprint(self) -> None:
        registry = {
            "version": 2,
            "connections": {
                "GROQ-01": {
                    "connection_id": "GROQ-01",
                    "provider": "groq",
                    "key_fingerprint": "",
                },
                "GROQ-02": {
                    "connection_id": "GROQ-02",
                    "provider": "groq",
                    "key_fingerprint": "",
                },
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "groq_keys.txt"
            path.write_text("secret-one\nsecret-two\n", encoding="utf-8")
            from connection_manager import fingerprint

            registry["connections"]["GROQ-01"]["key_fingerprint"] = fingerprint("secret-one")
            registry["connections"]["GROQ-02"]["key_fingerprint"] = fingerprint("secret-two")
            import_provider("groq", path, registry, PROVIDER_PREFIXES["groq"])

            reordered = Path(temp_dir) / "groq_reordered.txt"
            reordered.write_text("secret-two\nsecret-one\n", encoding="utf-8")
            import_provider("groq", reordered, registry, PROVIDER_PREFIXES["groq"])

        self.assertEqual(
            registry["connections"]["GROQ-01"]["key_fingerprint"],
            fingerprint("secret-one"),
        )
        self.assertEqual(
            registry["connections"]["GROQ-02"]["key_fingerprint"],
            fingerprint("secret-two"),
        )

    def test_labeled_rotation_preserves_connection_id(self) -> None:
        registry = {
            "version": 2,
            "connections": {
                "OR-01": {
                    "connection_id": "OR-01",
                    "provider": "openrouter",
                    "key_fingerprint": "old",
                    "status": "VALIDATED",
                    "active": True,
                },
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "openrouter_keys.txt"
            path.write_text("OR-01=new-secret-value\n", encoding="utf-8")
            import_provider("openrouter", path, registry, PROVIDER_PREFIXES["openrouter"])

        self.assertIn("OR-01", registry["connections"])
        self.assertEqual(registry["connections"]["OR-01"]["status"], "KEY_ROTATED")
        self.assertFalse(registry["connections"]["OR-01"]["active"])
        self.assertEqual(
            registry["connections"]["OR-01"]["key_fingerprint"],
            __import__("connection_manager").fingerprint("new-secret-value"),
        )

    def test_new_unlabeled_secret_gets_next_available_id(self) -> None:
        registry = {
            "version": 2,
            "connections": {
                "GROQ-01": {
                    "connection_id": "GROQ-01",
                    "provider": "groq",
                    "key_fingerprint": "existing",
                },
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "groq_keys.txt"
            path.write_text("new-secret\n", encoding="utf-8")
            import_provider("groq", path, registry, PROVIDER_PREFIXES["groq"])

        self.assertIn("GROQ-02", registry["connections"])
        self.assertEqual(
            registry["connections"]["GROQ-02"]["provider"],
            "groq",
        )

    def test_load_registry_declares_authoritative_role_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry_path = root / "connections.json"
            registry_path.write_text(
                '{"version": 2, "role_source": "roles.json", "connections": {}}',
                encoding="utf-8",
            )
            with patch("connection_manager.REGISTRY_FILE", registry_path):
                loaded = load_registry()

        self.assertEqual(loaded["role_source"], "config/registry.json")

    def test_save_registry_persists_authoritative_role_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "connections.json"
            with patch("connection_manager.REGISTRY_FILE", path):
                save_registry({"version": 3, "connections": {}})
                saved = path.read_text(encoding="utf-8")

        self.assertIn('"role_source": "config/registry.json"', saved)


if __name__ == "__main__":
    unittest.main(verbosity=2)
