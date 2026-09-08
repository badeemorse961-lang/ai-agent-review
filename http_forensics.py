from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from secret_redaction import redact_text


MAX_ERROR_MESSAGE_CHARS = 300


@dataclass(frozen=True)
class HTTPForensicEvidence:
    """Bounded, secret-redacted HTTP evidence safe for benchmark persistence."""

    request_classification: str
    http_status: int | None
    status_category: str
    sanitized_error_code: str | None
    sanitized_error_message: str | None
    elapsed_ms: float | None
    connection_id: str | None = None
    provider: str | None = None
    model: str | None = None
    task_id: str | None = None
    task_class: str | None = None
    repeat: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_http_status(status_code: int) -> str:
    if status_code == 401:
        return "AUTHENTICATION_FAILURE"
    if status_code == 403:
        return "AUTHORIZATION_ACCESS_FAILURE"
    if status_code == 408:
        return "REQUEST_TIMEOUT"
    if status_code == 429:
        return "RATE_LIMIT"
    if 400 <= status_code <= 499:
        return "INVALID_REQUEST"
    if 500 <= status_code <= 599:
        return "PROVIDER_TRANSIENT_FAILURE"
    if 200 <= status_code <= 299:
        return "OK"
    return f"HTTP_{status_code}"


def sanitize_error_payload(
    payload: Any,
    *,
    secrets: Sequence[str] = (),
) -> tuple[str | None, str | None]:
    """Extract only bounded, secret-redacted error code/message from a provider body."""
    if not isinstance(payload, Mapping):
        return None, None
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None, None

    code = error.get("code")
    message = error.get("message")

    sanitized_code = None
    if isinstance(code, (str, int)):
        sanitized_code = redact_text(str(code), secrets=secrets)[:MAX_ERROR_MESSAGE_CHARS]

    sanitized_message = None
    if isinstance(message, str):
        sanitized_message = redact_text(
            message[:MAX_ERROR_MESSAGE_CHARS],
            secrets=secrets,
        )

    return sanitized_code, sanitized_message


def build_http_forensic_evidence(
    *,
    request_classification: str,
    http_status: int | None,
    status_category: str | None = None,
    sanitized_error_code: str | None = None,
    sanitized_error_message: str | None = None,
    elapsed_ms: float | None = None,
    connection_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    task_id: str | None = None,
    task_class: str | None = None,
    repeat: int | None = None,
    secrets: Sequence[str] = (),
) -> HTTPForensicEvidence:
    message = (
        redact_text(
            sanitized_error_message[:MAX_ERROR_MESSAGE_CHARS],
            secrets=secrets,
        )
        if isinstance(sanitized_error_message, str)
        else None
    )
    code = (
        redact_text(
            sanitized_error_code[:MAX_ERROR_MESSAGE_CHARS],
            secrets=secrets,
        )
        if isinstance(sanitized_error_code, str)
        else None
    )
    category = status_category
    if category is None:
        category = classify_http_status(http_status) if http_status is not None else "NETWORK_OR_TRANSPORT_FAILURE"
    return HTTPForensicEvidence(
        request_classification=request_classification,
        http_status=http_status,
        status_category=category,
        sanitized_error_code=code,
        sanitized_error_message=message,
        elapsed_ms=elapsed_ms,
        connection_id=connection_id,
        provider=provider,
        model=model,
        task_id=task_id,
        task_class=task_class,
        repeat=repeat,
    )
