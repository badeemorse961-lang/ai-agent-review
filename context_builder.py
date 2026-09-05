from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_MAX_CHARS = 24000

SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|token|secret|password|authorization|credential)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._-]{20,})",
    re.IGNORECASE,
)


class ContextBuildError(ValueError):
    """Raised when an evidence bundle cannot be converted safely."""


class ContextBuilder:
    """Build bounded, prioritized, redacted planning context from local evidence.

    The builder is model-agnostic and does not authorize execution. It only
    prepares evidence for a future leader/planner boundary.
    """

    PRIORITY = (
        "classification",
        "gap_compliance",
        "specification",
        "current_state",
        "manifest",
    )

    def __init__(self, max_chars: int = DEFAULT_MAX_CHARS) -> None:
        if not isinstance(max_chars, int) or max_chars < 1000:
            raise ContextBuildError("max_chars must be an integer >= 1000")
        self.max_chars = max_chars

    def build(self, bundle: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(bundle, dict):
            raise ContextBuildError("Evidence bundle must be a mapping")

        summary = self._build_summary(bundle)
        sections: dict[str, Any] = {}
        remaining = self.max_chars

        for section_name in self.PRIORITY:
            if section_name not in bundle:
                continue
            safe = self._redact(deepcopy(bundle[section_name]))
            candidate_size = len(self._encode({section_name: safe}))
            if candidate_size <= remaining:
                sections[section_name] = safe
                remaining -= candidate_size
                continue

            compact = self._compact(section_name, safe, remaining)
            if compact is not None:
                compact_size = len(self._encode({section_name: compact}))
                if compact_size <= remaining:
                    sections[section_name] = compact
                    remaining -= compact_size

        envelope = {
            "schema_version": SCHEMA_VERSION,
            "context_kind": "leader_planning_context",
            "source_schema_version": bundle.get("schema_version"),
            "workspace": bundle.get("workspace"),
            "summary": summary,
            "sections": sections,
            "authority_note": (
                "Context is evidence for planning only. It does not authorize "
                "filesystem mutation, command execution, or policy overrides."
            ),
        }

        serialized = self._encode(envelope)
        if len(serialized) > self.max_chars:
            envelope = self._minimal_envelope(bundle, summary)
            serialized = self._encode(envelope)

        if len(serialized) > self.max_chars:
            raise ContextBuildError("Unable to fit safe context within max_chars")

        self._assert_no_secrets(envelope)
        envelope["char_count"] = len(serialized)
        envelope["truncated"] = len(serialized) < len(
            self._encode(self._redact(deepcopy(bundle)))
        )
        return envelope

    @classmethod
    def _redact(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if cls._is_sensitive_key(str(key)) else cls._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._redact(item) for item in value]
        if isinstance(value, str) and SENSITIVE_VALUE_RE.search(value):
            return SENSITIVE_VALUE_RE.sub("[REDACTED]", value)
        return value

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        return bool(SENSITIVE_KEY_RE.search(key))

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def _compact(cls, section_name: str, value: Any, remaining: int) -> Any | None:
        if remaining < 500:
            return None

        if isinstance(value, dict):
            preferred: dict[str, Any] = {}
            for key in (
                "summary",
                "state",
                "confidence",
                "requirements",
                "gaps",
                "unknown",
            ):
                if key in value:
                    preferred[key] = value[key]
            if preferred and len(cls._encode({section_name: preferred})) <= remaining:
                return preferred

        encoded = cls._encode(value)
        limit = max(200, remaining - len(section_name) - 24)
        if len(encoded) <= limit:
            return value
        return {
            "truncated": True,
            "preview": encoded[: max(0, limit - 48)],
        }

    @staticmethod
    def _build_summary(bundle: dict[str, Any]) -> dict[str, Any]:
        classification = bundle.get("classification", {}) or {}
        specification = bundle.get("specification", {}) or {}
        compliance = bundle.get("gap_compliance", {}).get("summary", {}) or {}
        return {
            "state": classification.get("state"),
            "confidence": classification.get("confidence"),
            "requirement_count": specification.get("requirement_count", 0),
            "verified": compliance.get("verified", 0),
            "implemented_unverified": compliance.get("implemented_unverified", 0),
            "tested_unimplemented": compliance.get("tested_unimplemented", 0),
            "gaps": compliance.get("gaps", 0),
            "unknown": compliance.get("unknown", 0),
            "autonomous_compliance_proven": compliance.get(
                "autonomous_compliance_proven", False
            ),
        }

    @staticmethod
    def _minimal_envelope(
        bundle: dict[str, Any], summary: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "context_kind": "leader_planning_context",
            "source_schema_version": bundle.get("schema_version"),
            "summary": summary,
            "sections": {},
            "authority_note": (
                "Context is evidence for planning only and does not authorize execution."
            ),
        }

    @classmethod
    def _assert_no_secrets(cls, value: Any) -> None:
        serialized = cls._encode(value)
        if SENSITIVE_VALUE_RE.search(serialized):
            raise ContextBuildError("Secret-like value detected after redaction")


if __name__ == "__main__":
    print("ContextBuilder ready")
