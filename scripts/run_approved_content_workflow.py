"""Run Research -> Outline -> Script for the approved pipeline topic."""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import PROJECTS_DIR
from modules.content_workflow import ContentWorkflow
from modules.topic_intelligence.models import OpportunityReport


def main() -> int:
    artifacts_directory = Path(
        os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts")
    )
    selection_path = artifacts_directory / "topic_selection.json"
    candidates_path = artifacts_directory / "topic_candidates.json"
    if not selection_path.exists() or not candidates_path.exists():
        raise FileNotFoundError("Approved topic artifacts are missing.")

    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    candidates_payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    report_payload = {
        "report_id": candidates_payload["report_id"],
        "request": candidates_payload["request"],
        "provider": candidates_payload["provider"],
        "candidates": candidates_payload["candidates"],
    }
    report = OpportunityReport.model_validate(report_payload)
    result = ContentWorkflow(Path(PROJECTS_DIR)).run(
        topic=selection["topic"],
        report=report,
        candidate_id=selection["candidate_id"],
        target_duration_seconds=selection["target_duration_seconds"],
        minimum_duration_seconds=selection["minimum_duration_seconds"],
        constraints=selection["constraints"],
    )

    output = {
        "project_id": result.project.project_id,
        "project_path": str(result.project_path),
        "topic": selection["topic"],
        "status": result.project.status,
        "completed_stages": ["research", "research_validation", "outline", "script", "packaging"],
        "test_run": True,
        "public_publish_allowed": False,
    }
    output_path = artifacts_directory / "content_workflow_result.json"
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
