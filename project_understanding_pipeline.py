from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from current_state_analyzer import CurrentStateAnalyzer
from gap_compliance import GapComplianceAnalyzer
from project_scanner import ProjectScanner
from project_state_classifier import ProjectStateClassifier
from specification_analyzer import SpecificationAnalyzer


SCHEMA_VERSION = 1


class ProjectUnderstandingPipeline:
    """Compose local project-understanding stages without model inference.

    The coordinator is intentionally read-only with respect to the active
    project. It creates an in-memory evidence bundle and does not mutate source
    files, call network services, or decide whether execution is authorized.
    """

    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()

    def analyze(
        self,
        execution_evidence: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        manifest = ProjectScanner(
            workspace_root=self.workspace_root,
            output_file=self.workspace_root / ".project_manifest.pipeline.json",
        ).scan()

        classification = ProjectStateClassifier().classify(manifest)
        specification = SpecificationAnalyzer(self.workspace_root).analyze()
        current_state = CurrentStateAnalyzer(self.workspace_root).analyze(
            specification=specification,
            manifest=manifest,
            execution_evidence=execution_evidence,
        )
        compliance = GapComplianceAnalyzer().analyze(
            specification=specification,
            current_state=current_state,
        )

        return {
            "schema_version": SCHEMA_VERSION,
            "workspace": str(self.workspace_root),
            "manifest": manifest,
            "classification": {
                "state": classification.state,
                "confidence": classification.confidence,
                "rationale": classification.rationale,
                "unresolved_requirements": classification.unresolved_requirements,
                "autonomous_start_allowed": classification.autonomous_start_allowed,
            },
            "specification": specification,
            "current_state": current_state,
            "gap_compliance": compliance,
            "authority_note": (
                "This bundle is evidence for planning; it is not an execution "
                "authorization and cannot override project rules or safety gates."
            ),
        }

    @staticmethod
    def summarize(bundle: dict[str, Any]) -> dict[str, Any]:
        classification = bundle.get("classification", {})
        specification = bundle.get("specification", {})
        compliance = bundle.get("gap_compliance", {}).get("summary", {})

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


if __name__ == "__main__":
    root = Path.cwd()
    bundle = ProjectUnderstandingPipeline(root).analyze()
    print("Project understanding pipeline completed.")
    print(ProjectUnderstandingPipeline.summarize(bundle))
