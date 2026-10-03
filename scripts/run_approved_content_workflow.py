"""Run Research -> Outline -> Script for the approved pipeline topic."""

import json
import os
import sys
import tarfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import PROJECTS_DIR
from modules.content_workflow import ContentWorkflow
from modules.production_state import ProductionStateStore
from modules.project.manager import ProjectManager
from modules.topic_intelligence.models import OpportunityReport, TopicDiscoveryRequest


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
    request_payload = candidates_payload.get("request")
    if request_payload is None:
        request_payload = TopicDiscoveryRequest(
            niche="RITZZ mixed curiosity explainers",
            limit=20,
            pipeline_topic_gate=True,
        ).model_dump(mode="json")
        print("Discovery request was missing; using legacy pipeline defaults.")
    report_payload = {
        "report_id": candidates_payload["report_id"],
        "request": request_payload,
        "provider": candidates_payload["provider"],
        "candidates": candidates_payload["candidates"],
    }
    report = OpportunityReport.model_validate(report_payload)
    workflow_kwargs = {
        "topic": selection["topic"],
        "report": report,
        "candidate_id": selection["candidate_id"],
        "target_duration_seconds": selection["target_duration_seconds"],
        "minimum_duration_seconds": selection["minimum_duration_seconds"],
        "constraints": selection["constraints"],
    }
    production_id = os.environ.get("RITZZ_PRODUCTION_ID")
    state_path = artifacts_directory / "production_state.json"
    saved_project_id = None
    if production_id is not None and state_path.is_file():
        state = ProductionStateStore(state_path, artifacts_directory).resume(production_id)
        saved_project_id = state.get("project_id")
        if not saved_project_id and state.get("current_stage") == "content_preparation":
            project = ProjectManager(Path(PROJECTS_DIR)).create_project(selection["topic"])
            saved_project_id = project.project_id
            ProductionStateStore(state_path, artifacts_directory).set_project_id(
                saved_project_id
            )
    if saved_project_id:
        workflow_kwargs["project_id"] = saved_project_id
        workflow_kwargs["force_refresh_research"] = True
        print(f"Resuming content preparation for project {saved_project_id}; refreshing research.")
    workflow = ContentWorkflow(Path(PROJECTS_DIR))
    state_store = (
        ProductionStateStore(state_path, artifacts_directory)
        if production_id is not None and state_path.is_file()
        else None
    )
    try:
        result = workflow.run(**workflow_kwargs)
    except Exception as exc:
        project_id = saved_project_id
        if project_id:
            project = workflow.manager.load_project(project_id)
            project_directory = workflow.manager.get_project_path(project)
            archive_path = artifacts_directory / "content-project.tar.gz"
            with tarfile.open(archive_path, "w:gz") as archive:
                archive.add(project_directory, arcname=project_id)
            validation_path = project_directory / "research" / "research_validation.json"
            qa_path = project_directory / "qa" / "qa_report.json"
            failure = {"error": str(exc)}
            if validation_path.is_file():
                failure["research_validation"] = json.loads(
                    validation_path.read_text(encoding="utf-8")
                )
            if qa_path.is_file():
                failure["qa_report"] = json.loads(qa_path.read_text(encoding="utf-8"))
            failure_path = artifacts_directory / "content_workflow_error.json"
            failure_path.write_text(json.dumps(failure, indent=2) + "\n", encoding="utf-8")
            if state_store and production_id is not None:
                state = state_store.resume(production_id)
                if state["current_stage"] == "content_preparation":
                    state_store.fail_stage(
                        "content_preparation",
                        str(exc),
                        ["content-project.tar.gz", "content_workflow_error.json"],
                        project_id=project_id,
                    )
        raise

    output = {
        "project_id": result.project.project_id,
        "project_path": str(result.project_path),
        "topic": selection["topic"],
        "status": result.project.status,
        "completed_stages": ["research", "research_validation", "outline", "script"],
        "test_run": True,
        "public_publish_allowed": False,
    }
    output_path = artifacts_directory / "content_workflow_result.json"
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    if state_store or result.project_path.is_dir():
        archive_path = artifacts_directory / "content-project.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(result.project_path, arcname=result.project.project_id)
    if state_store and production_id is not None:
        state = state_store.resume(production_id)
        if state["current_stage"] == "content_preparation":
            state_store.complete_stage(
                "content_preparation",
                ["content_workflow_result.json", "content-project.tar.gz"],
                project_id=result.project.project_id,
            )
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
