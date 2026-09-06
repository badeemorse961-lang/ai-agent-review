from __future__ import annotations

from groq_worker_health_check import safe_error
from secret_redaction import REPLACEMENT, SecretRedactor, redact_text


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_redacts_project_provider_key_formats() -> None:
    text = "groq=gsk_projectSECRET123 openrouter=sk-or-v1-projectSECRET123 generic=sk-project-secret-12345"

    redacted = redact_text(text)

    assert "gsk_projectSECRET123" not in redacted
    assert "sk-or-v1-projectSECRET123" not in redacted
    assert "sk-project-secret-12345" not in redacted
    assert redacted.count(REPLACEMENT) == 3


def test_redacts_bearer_and_named_assignments() -> None:
    text = "Authorization: Bearer super-secret-token api_key=my-api-key password=hunter2 token=secret-token"

    redacted = redact_text(text)

    assert "super-secret-token" not in redacted
    assert "my-api-key" not in redacted
    assert "hunter2" not in redacted
    assert "secret-token" not in redacted
    assert "Bearer [REDACTED]" in redacted
    assert "api_key=[REDACTED]" in redacted
    assert "password=[REDACTED]" in redacted
    assert "token=[REDACTED]" in redacted


def test_explicit_secret_redaction_handles_non_standard_values() -> None:
    redactor = SecretRedactor.from_secrets(("custom-secret-value", "another-secret"))

    redacted = redactor.redact_text("custom-secret-value / another-secret")

    assert redacted == f"{REPLACEMENT} / {REPLACEMENT}"


def test_redacts_nested_values_in_mappings() -> None:
    redactor = SecretRedactor.from_secrets(("custom-secret-value",))

    result = redactor.redact_value(
        {
            "message": "custom-secret-value",
            "items": ["api_key=abc123", "safe"],
        }
    )

    assert result == {
        "message": REPLACEMENT,
        "items": ["api_key=[REDACTED]", "safe"],
    }


def test_groq_provider_errors_are_redacted_before_persistence() -> None:
    secret = "gsk_provider-error-secret-12345"
    response = FakeResponse(
        {
            "error": {
                "code": "invalid_request",
                "message": f"authorization failed for {secret}",
            }
        }
    )

    redacted = safe_error(response)

    assert redacted is not None
    assert secret not in redacted
    assert "[REDACTED]" in redacted
