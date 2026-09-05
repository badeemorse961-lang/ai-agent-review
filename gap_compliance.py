from __future__ import annotations

from typing import Any


SCHEMA_VERSION = 1
VALID_STATUSES = {
    "VERIFIED",
    "IMPLEMENTED_UNVERIFIED",
    "TESTED_UNIMPLEMENTED",
    "GAP",
    "UNKNOWN",
}


class GapComplianceAnalyzer:
    """Compare stated requirements with current-state evidence.

    A requirement is called VERIFIED only when explicit execution evidence is
    supplied. Static source/test matches never become a false proof of runtime
    correctness.
    """

    def analyze(
        self,
        specification: dict[str, Any],
        current_state: dict[str, Any],
    ) -> dict[str, Any]:
        state_by_id = {
            item.get("requirement_id"): item
            for item in current_state.get("requirements", [])
            if isinstance(item, dict) and item.get("requirement_id")
        }

        results: list[dict[str, Any]] = []
        counts = {status: 0 for status in VALID_STATUSES}

        for requirement in specification.get("requirements", []):
            if not isinstance(requirement, dict):
                continue

            requirement_id = requirement.get("requirement_id")
            evidence = state_by_id.get(requirement_id, {})
            status = self._status(evidence)
            counts[status] += 1

            results.append(
                {
                    "requirement_id": requirement_id,
                    "source": requirement.get("source"),
                    "line": requirement.get("line"),
                    "text": requirement.get("text"),
                    "kind": requirement.get("kind"),
                    "strength": requirement.get("strength"),
                    "status": status,
                    "implementation_evidence": evidence.get("implementation_evidence", []),
                    "test_evidence": evidence.get("test_evidence", []),
                    "execution_evidence": evidence.get("execution_evidence"),
                    "rationale": self._rationale(evidence, status),
                }
            )

        return {
            "schema_version": SCHEMA_VERSION,
            "analyzer": {
                "name": "GapComplianceAnalyzer",
                "version": "v1",
            },
            "summary": {
                "requirement_count": len(results),
                "verified": counts["VERIFIED"],
                "implemented_unverified": counts["IMPLEMENTED_UNVERIFIED"],
                "tested_unimplemented": counts["TESTED_UNIMPLEMENTED"],
                "gaps": counts["GAP"],
                "unknown": counts["UNKNOWN"],
                "autonomous_compliance_proven": (
                    counts["GAP"] == 0
                    and counts["UNKNOWN"] == 0
                    and counts["VERIFIED"] == len(results)
                ),
            },
            "requirements": results,
        }

    @staticmethod
    def _status(evidence: dict[str, Any]) -> str:
        execution = evidence.get("execution_evidence")
        if isinstance(execution, dict):
            passed = execution.get("passed")
            if passed is True:
                return "VERIFIED"
            if passed is False:
                return "GAP"

        implementation = evidence.get("implementation_evidence") or []
        tests = evidence.get("test_evidence") or []

        if implementation and tests:
            return "IMPLEMENTED_UNVERIFIED"
        if implementation:
            return "IMPLEMENTED_UNVERIFIED"
        if tests:
            return "TESTED_UNIMPLEMENTED"

        return "UNKNOWN"

    @staticmethod
    def _rationale(evidence: dict[str, Any], status: str) -> str:
        if status == "VERIFIED":
            return "Explicit execution evidence reports this requirement as passed."
        if status == "GAP":
            execution = evidence.get("execution_evidence")
            if isinstance(execution, dict) and execution.get("reason"):
                return f"Execution evidence reports failure: {execution['reason']}"
            return "No successful implementation proof was established."
        if status == "IMPLEMENTED_UNVERIFIED":
            return "Static implementation evidence exists; runtime correctness is not proven."
        if status == "TESTED_UNIMPLEMENTED":
            return "Tests reference the requirement, but implementation evidence was not found."
        return "No direct implementation or test evidence was found."
