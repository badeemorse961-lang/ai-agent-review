from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence


REPLACEMENT = "[REDACTED]"

# High-signal credential forms used by this project and common tooling.
_PATTERN_RE = re.compile(
    r"(?ix)"
    r"(?P<bearer_header>\bAuthorization\s*[:=]\s*)?(?P<bearer>Bearer\s+)[A-Za-z0-9._~+\-/=\[\]REDCTED]+"
    r"|(?P<groq>\bgsk_[A-Za-z0-9_-]{8,})"
    r"|(?P<openrouter>\bsk-or-v1-[A-Za-z0-9_-]{8,})"
    r"|(?P<generic>\bsk-[A-Za-z0-9_-]{12,})"
    r"|(?P<assignment>\b(?:api[_-]?key|access[_-]?token|password|secret|token)\s*[:=]\s*)[^\s,;&]+"
    r"|(?P<query>\b(?:api[_-]?key|access[_-]?token|token|secret|password)=[^\s&]+)"
)


@dataclass(frozen=True)
class SecretRedactor:
    """Redact known credential values plus high-signal credential patterns."""

    secrets: tuple[str, ...] = ()

    @classmethod
    def from_secrets(cls, secrets: Sequence[str]) -> "SecretRedactor":
        normalized = tuple(
            sorted(
                {
                    str(secret).strip()
                    for secret in secrets
                    if isinstance(secret, str) and len(secret.strip()) >= 4
                },
                key=len,
                reverse=True,
            )
        )
        return cls(normalized)

    def redact_text(self, value: object) -> str:
        text = "" if value is None else str(value)
        text = _PATTERN_RE.sub(self._replace_match, text)
        for secret in self.secrets:
            if secret:
                text = text.replace(secret, REPLACEMENT)
        return text

    def redact_mapping(self, value: Mapping[object, object]) -> dict[str, object]:
        return {
            str(key): self.redact_value(item)
            for key, item in value.items()
        }

    def redact_value(self, value: object) -> object:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            return self.redact_mapping(value)
        if isinstance(value, (list, tuple)):
            return [self.redact_value(item) for item in value]
        return value

    @staticmethod
    def _replace_match(match: re.Match[str]) -> str:
        if match.group("bearer"):
            prefix = match.group("bearer_header") or ""
            return f"{prefix}{match.group('bearer')}{REPLACEMENT}"
        if match.group("assignment"):
            return f"{match.group('assignment')}{REPLACEMENT}"
        if match.group("query"):
            name = match.group("query").split("=", 1)[0]
            return f"{name}={REPLACEMENT}"
        return REPLACEMENT


DEFAULT_REDACTOR = SecretRedactor()


def redact_text(value: object, *, secrets: Sequence[str] = ()) -> str:
    if secrets:
        return SecretRedactor.from_secrets(secrets).redact_text(value)
    return DEFAULT_REDACTOR.redact_text(value)
