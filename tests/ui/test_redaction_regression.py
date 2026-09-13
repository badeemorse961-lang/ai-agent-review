# Redaction regression for Batch 1 — verify SecretRedactor excludes secrets before projection.

import sys, unittest
sys.path.insert(0, "/projects")

from secret_redaction import SecretRedactor, redact_text

class TestBatch1Redaction(unittest.TestCase):
    def test_redactor_removes_secret_patterns(self):
        redactor = SecretRedactor.from_secrets(["TEST_KEY_123"])
        result = redactor.redact_text("key: TEST_KEY_123 here")
        self.assertNotIn("TEST_KEY_123", result)

    def test_empty_secret_projection(self):
        redactor = SecretRedactor.from_secrets([])
        result = redactor.redact_text("project: safe")
        self.assertEqual(result, "project: safe")

if __name__ == "__main__":
    unittest.main()
