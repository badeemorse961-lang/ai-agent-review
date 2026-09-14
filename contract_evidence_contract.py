from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping

@dataclass(frozen=True)
class EvidenceArtifact:
    status: str  # SUCCEEDED / FAILED / SAFE_STOP
    fingerprint: str  # key fingerprint only; never secret value
    checkpoint_id: str
    validation_evidence: Mapping[str, Any]
    failure: dict | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "fingerprint": self.fingerprint,
            "checkpoint_id": self.checkpoint_id,
            "validation_evidence": dict(self.validation_evidence),
            "failure": dict(self.failure) if self.failure else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvidenceArtifact":
        if not isinstance(d, dict):
            raise ValueError("EvidenceArtifact requires dict")
        status = d.get("status")
        if status not in ("SUCCEEDED", "FAILED", "SAFE_STOP"):
            raise ValueError("EvidenceArtifact status must be SUCCEEDED/FAILED/SAFE_STOP")
        fp = d.get("fingerprint")
        if not isinstance(fp, str) or not fp.strip():
            raise ValueError("EvidenceArtifact fingerprint must be non-empty string")
        if "sk-" in fp or fp.startswith("Bearer ") or "secret_value" in fp:
            raise ValueError("EvidenceArtifact fingerprint invalid or secret exposure")
        checkpoint = d.get("checkpoint_id")
        if not isinstance(checkpoint, str) or not checkpoint.strip():
            raise ValueError("EvidenceArtifact requires non-empty checkpoint_id")
        evidence = d.get("validation_evidence")
        if not isinstance(evidence, dict):
            raise ValueError("EvidenceArtifact validation_evidence must be dict")
        status = d.get("status")
        passed = evidence.get("passed")
        # SUCCEEDED requires passed=True; FAILED/SAFE_STOP must NOT claim passed=True
        if status == "SUCCEEDED":
            if passed is not True:
                raise ValueError("EvidenceArtifact SUCCEEDED requires passed=True validation evidence")
        elif status in ("FAILED", "SAFE_STOP"):
            if passed is True:
                raise ValueError(f"EvidenceArtifact {status} must not claim passed=True (must carry failure/stop evidence)")
        else:
            raise ValueError("EvidenceArtifact status must be SUCCEEDED/FAILED/SAFE_STOP")
        failure = d.get("failure")
        if status == "FAILED":
            if not isinstance(failure, dict) or not failure.get("message"):
                raise ValueError("EvidenceArtifact FAILED must include bounded failure evidence with message")
        elif status == "SAFE_STOP":
            # Must have either failure with message, or validation_evidence with a reason field
            has_stop_evidence = (isinstance(failure, dict) and failure.get("message")) or (isinstance(evidence.get("reason"), str) and evidence.get("reason").strip())
            if not has_stop_evidence:
                raise ValueError("EvidenceArtifact SAFE_STOP must include bounded safety-stop reason (failure.message or evidence.reason)")
        if failure is not None and not isinstance(failure, dict):
            raise ValueError("EvidenceArtifact failure must be dict or None")
        return cls(
            status=status,
            fingerprint=fp.strip(),
            checkpoint_id=checkpoint.strip(),
            validation_evidence=dict(evidence),
            failure=dict(failure) if failure else None,
        )
