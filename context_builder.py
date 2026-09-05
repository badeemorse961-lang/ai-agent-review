from __future__ import annotations

import json
import re
from typing import Any


SCHEMA_VERSION = 1
DEFAULT_MAX_CHARS = 12_000
DEFAULT_MAX_REQUIREMENTS = 100
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|token|secret|password|authorization|credential)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_RE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9_-]{20,}|Bearer\s+[A-Za-z0-9._-]{20,})",
    re.IGNORECASE,
)


class ContextBuilder:
    """Build a bounded, deterministic planning context from evidence.

    This component performs no network calls, no project execution, and no
    filesystem mutation. It only reshapes the existing evidence bundle into a
    compact structure suitable for a future leader/model boundary.

    The builder intentionally does not include source contents. Source-code
    selection and bounded excerpts are a separate trust/budget concern and
    should be added only after the evidence-only contract is proven.
    """

    def __init__(
        self,
        max_chars: int = DEFAULT_MAX_CHARS,
        max_requirements: int = DEFAULT_MAX_REQUIREMENTS,
    ) -> None:
        if max_chars < 512:
            raise ValueError("max_chars must be at least 512")
        if max_requirements < 1:
            raise ValueError("max_requirements must be positive")

        self.max_chars = max_chars
        self.max_requirements = max_requirements

    def build(self, bundle: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(bundle, dict):
            raise ValueError("ContextBuilder requires an evidence bundle object")

        classification = self._classification(bundle.get("classification"))
        specification = bundle.get("specification")
        compliance = bundle.get("gap_compliance")
        current_state = bundle.get("current_state")

        if not isinstance(specification, dict):
            specification = {}
        if not isinstance(compliance, dict):
            compliance = {}
        if not isinstance(current_state, dict):
            current_state = {}

        requirements = self._build_requirement_entries(
            specification.get("requirements"),
            compliance.get("requirements"),
            current_state.get("requirements"),
        )

        selected = requirements[: self.max_requirements]

        context = {
            "schema_version": SCHEMA_VERSION,
            "builder": {
                "name": "ContextBuilder",
                "version": "v1",
                "max_chars": self.max_chars,
                "max_requirements": self.max_requirements,
            },
            "authority": {
                "purpose": "planning_context",
                "execution_authorized": False,
                "mutation_allowed": False,
                "runtime_proof_required": True,
                "source_contents_included": False,
            },
            "project": {
                "state": classification["state"],
                "confidence": classification["confidence"],
                "rationale": classification["rationale"],
                "unresolved_requirements": classification["unresolved_requirements"],
                "autonomous_start_allowed": classification["autonomous_start_allowed"],
            },
            "compliance": self._compliance_summary(compliance.get("summary")),
            "requirements": selected,
        }
        context = self._redact(context)

        if len(self._serialize(context)) <= self.max_chars:
            self._assert_no_secrets(context)
            return context

        context = self._fit_budget(context)
        self._assert_no_secrets(context)
        return context

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

    @classmethod
    def _assert_no_secrets(cls, value: Any) -> None:
        serialized = cls._serialize(value)
        if cls._is_sensitive_key(serialized) or SENSITIVE_VALUE_RE.search(serialized):
            raise ValueError("Secret-like value detected after redaction")

    @staticmethod
    def _classification(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            value = {}

        return {
            "state": str(value.get("state") or "UNKNOWN"),
            "confidence": value.get("confidence"),
            "rationale": str(value.get("rationale") or "No classification rationale supplied."),
            "unresolved_requirements": int(value.get("unresolved_requirements") or 0),
            "autonomous_start_allowed": bool(value.get("autonomous_start_allowed", False)),
        }

    @staticmethod
    def _compliance_summary(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            value = {}

        allowed = {
            "requirement_count",
            "verified",
            "implemented_unverified",
            "tested_unimplemented",
            "gaps",
            "unknown",
            "autonomous_compliance_proven",
        }
        return {
            key: value.get(
                key,
                0 if key != "autonomous_compliance_proven" else False,
            )
            for key in sorted(allowed)
        }

    def _build_requirement_entries(
        self,
        specification_requirements: Any,
        compliance_requirements: Any,
        current_requirements: Any,
    ) -> list[dict[str, Any]]:
        specification_map = self._index_by_id(specification_requirements)
        compliance_map = self._index_by_id(compliance_requirements)
        current_map = self._index_by_id(current_requirements)

        ids = sorted(
            set(specification_map) | set(compliance_map) | set(current_map),
            key=str,
        )

        entries: list[dict[str, Any]] = []
        for requirement_id in ids:
            spec = specification_map.get(requirement_id, {})
            compliance = compliance_map.get(requirement_id, {})
            current = current_map.get(requirement_id, {})

            text = str(spec.get("text") or compliance.get("text") or "")
            source = spec.get("source") or compliance.get("source")
            line = spec.get("line") or compliance.get("line")
            status = compliance.get("status") or self._derive_status(current)

            entry = {
                "requirement_id": str(requirement_id),
                "text": text,
                "source": source,
                "line": line,
                "kind": spec.get("kind") or compliance.get("kind"),
                "strength": spec.get("strength") or compliance.get("strength"),
                "status": status,
                "priority": self._priority(status, current, spec),
                "implementation_paths": self._paths(
                    current,
                    "implementation_evidence",
                ),
                "test_paths": self._paths(current, "test_evidence"),
                "execution_evidence_present": (
                    current.get("execution_evidence") is not None
                ),
            }
            entries.append(entry)

        entries.sort(
            key=lambda item: (
                -int(item["priority"]),
                str(item["status"]),
                str(item["source"] or ""),
                int(item["line"] or 0),
                str(item["requirement_id"]),
            )
        )
        return entries

    @staticmethod
    def _index_by_id(value: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(value, list):
            return {}

        result: dict[str, dict[str, Any]] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            requirement_id = item.get("requirement_id")
            if not requirement_id:
                continue
            result[str(requirement_id)] = item
        return result

    @staticmethod
    def _derive_status(current: dict[str, Any]) -> str:
        execution = current.get("execution_evidence")
        if isinstance(execution, dict):
            if execution.get("passed") is True:
                return "VERIFIED"
            if execution.get("passed") is False:
                return "GAP"

        implementation = current.get("implementation_evidence") or []
        tests = current.get("test_evidence") or []
        if implementation:
            return "IMPLEMENTED_UNVERIFIED"
        if tests:
            return "TESTED_UNIMPLEMENTED"
        return "UNKNOWN"

    @staticmethod
    def _priority(
        status: Any,
        current: dict[str, Any],
        specification: dict[str, Any],
    ) -> int:
        status_weight = {
            "GAP": 100,
            "UNKNOWN": 90,
            "TESTED_UNIMPLEMENTED": 80,
            "IMPLEMENTED_UNVERIFIED": 70,
            "VERIFIED": 10,
        }
        priority = status_weight.get(str(status), 60)
        if specification.get("strength") == "mandatory":
            priority += 5
        if current.get("execution_evidence") is not None:
            priority += 2
        return priority

    @staticmethod
    def _paths(current: dict[str, Any], field: str) -> list[str]:
        value = current.get(field) or []
        if not isinstance(value, list):
            return []

        paths = [
            str(item["path"])
            for item in value
            if isinstance(item, dict) and item.get("path")
        ]
        return sorted(set(paths), key=str.lower)

    @staticmethod
    def _serialize(value: dict[str, Any]) -> str:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _fit_budget(self, context: dict[str, Any]) -> dict[str, Any]:
        original_count = len(context["requirements"])

        for end in range(original_count, -1, -1):
            requirements = context["requirements"][:end]
            omitted = original_count - end
            candidate = dict(context)
            candidate["requirements"] = requirements
            candidate["budget"] = {
                "truncated": omitted > 0,
                "included_requirements": end,
                "omitted_requirements": omitted,
            }
            if len(self._serialize(candidate)) <= self.max_chars:
                return candidate

        raise ValueError(
            "ContextBuilder fixed metadata exceeds max_chars; increase max_chars."
        )


def build_context(
    bundle: dict[str, Any],
    max_chars: int = DEFAULT_MAX_CHARS,
    max_requirements: int = DEFAULT_MAX_REQUIREMENTS,
) -> dict[str, Any]:
    """Functional wrapper around :class:`ContextBuilder`."""
    return ContextBuilder(
        max_chars=max_chars,
        max_requirements=max_requirements,
    ).build(bundle)


if __name__ == "__main__":
    print("ContextBuilder module ready.")