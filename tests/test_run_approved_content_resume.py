import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.production_state import ProductionStateStore
from modules.project.manager import ProjectManager
from modules.topic_intelligence.models import (
    OpportunityCandidate,
    TopicDiscoveryRequest,
)
from scripts import run_approved_content_workflow


def _prepare_failed_content_stage(artifacts_directory):
    candidate = OpportunityCandidate(
        candidate_id="candidate-1",
        topic="How Ancient People Moved Giant Things",
        provider="fixture",
    )
    (artifacts_directory / "topic_candidates.json").write_text(
        json.dumps(
            {
                "report_id": "report-1",
                "provider": "fixture",
                "request": TopicDiscoveryRequest().model_dump(mode="json"),
                "candidates": [candidate.model_dump(mode="json")],
            }
        ),
        encoding="utf-8",
    )
    (artifacts_directory / "topic_candidates.md").write_text(
        "Candidate", encoding="utf-8"
    )
    (artifacts_directory / "topic_discovery_diagnostics.json").write_text(
        "{}",
        encoding="utf-8",
    )
    selection = {
        "candidate_id": candidate.candidate_id,
        "topic": candidate.topic,
        "target_duration_seconds": 480,
        "minimum_duration_seconds": 480,
        "constraints": [],
    }
    (artifacts_directory / "topic_selection.json").write_text(
        json.dumps(selection),
        encoding="utf-8",
    )

    store = ProductionStateStore(
        artifacts_directory / "production_state.json",
        artifacts_directory,
    )
    store.initialize("production-1")
    store.start_stage("topic_discovery")
    store.complete_stage(
        "topic_discovery",
        [
            "topic_candidates.json",
            "topic_candidates.md",
            "topic_discovery_diagnostics.json",
        ],
    )
    store.start_stage("topic_selection")
    store.complete_stage("topic_selection", ["topic_selection.json"])
    store.start_stage("content_preparation")


def test_failed_content_run_saves_details_and_resume_reuses_project(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)
    artifacts_directory = Path(".pipeline-artifacts")
    artifacts_directory.mkdir()
    projects_directory = tmp_path / "projects"
    _prepare_failed_content_stage(artifacts_directory)
    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(artifacts_directory))
    monkeypatch.setenv("RITZZ_PRODUCTION_ID", "production-1")
    monkeypatch.setattr(
        run_approved_content_workflow,
        "PROJECTS_DIR",
        projects_directory,
    )
    captured = {}

    class FailedContentWorkflow:
        def __init__(self, directory):
            self.manager = ProjectManager(directory)

        def run(self, **kwargs):
            project = self.manager.load_project(kwargs["project_id"])
            project_path = self.manager.get_project_path(project)
            validation_path = project_path / "research" / "research_validation.json"
            validation_path.write_text(
                json.dumps(
                    {
                        "status": "FAIL",
                        "issues": ["A high-importance claim has no source."],
                    }
                ),
                encoding="utf-8",
            )
            qa_path = project_path / "qa" / "qa_report.json"
            qa_path.parent.mkdir(parents=True)
            qa_path.write_text(
                json.dumps({"stages": {"research": []}}), encoding="utf-8"
            )
            raise RuntimeError(
                f"Content workflow failed for project {project.project_id}: "
                "Research validation failed."
            )

    monkeypatch.setattr(
        run_approved_content_workflow,
        "ContentWorkflow",
        FailedContentWorkflow,
    )

    with pytest.raises(RuntimeError, match="Research validation failed"):
        run_approved_content_workflow.main()

    failure = json.loads(
        (artifacts_directory / "content_workflow_error.json").read_text(
            encoding="utf-8"
        )
    )
    assert failure["research_validation"]["issues"] == [
        "A high-importance claim has no source."
    ]
    assert (artifacts_directory / "content-project.tar.gz").is_file()
    failed_state = ProductionStateStore(
        artifacts_directory / "production_state.json",
        artifacts_directory,
    ).resume("production-1")
    project_id = failed_state["project_id"]
    assert failed_state["stages"]["content_preparation"]["status"] == "failed"
    assert (
        "Research validation failed"
        in failed_state["stages"]["content_preparation"]["error"]
    )
    failed_project = ProjectManager(projects_directory).load_project(project_id)
    failed_project_directory = ProjectManager(projects_directory).get_project_path(
        failed_project
    )
    with tarfile.open(
        artifacts_directory / "content-project.tar.gz",
        "r:gz",
    ) as archive:
        assert f"{failed_project_directory.name}/project.json" in archive.getnames()

    ProductionStateStore(
        artifacts_directory / "production_state.json",
        artifacts_directory,
    ).start_stage("content_preparation")

    class SuccessfulContentWorkflow:
        def __init__(self, directory):
            self.manager = ProjectManager(directory)

        def run(self, **kwargs):
            captured.update(kwargs)
            project = self.manager.load_project(kwargs["project_id"])
            return SimpleNamespace(
                project=project,
                project_path=self.manager.get_project_path(project),
            )

    monkeypatch.setattr(
        run_approved_content_workflow,
        "ContentWorkflow",
        SuccessfulContentWorkflow,
    )
    assert run_approved_content_workflow.main() == 0
    assert captured["project_id"] == project_id
    assert captured["force_refresh_research"] is True
    assert len(list(projects_directory.iterdir())) == 1
    assert "refreshing research" in capsys.readouterr().out
    completed_state = ProductionStateStore(
        artifacts_directory / "production_state.json",
        artifacts_directory,
    ).resume("production-1")
    assert completed_state["current_stage"] is None
    assert completed_state["stages"]["content_preparation"]["status"] == "completed"
    project = ProjectManager(projects_directory).load_project(project_id)
    project_directory = ProjectManager(projects_directory).get_project_path(project)
    with tarfile.open(
        artifacts_directory / "content-project.tar.gz",
        "r:gz",
    ) as archive:
        assert f"{project_directory.name}/project.json" in archive.getnames()


def test_content_workflow_job_does_not_complete_checkpoint_twice():
    workflow_path = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "ritzz-pipeline.yml"
    )
    workflow_text = workflow_path.read_text(encoding="utf-8")

    assert "      - name: Run approved content workflow" in workflow_text
    assert "      - name: Archive generated project artifacts" not in workflow_text
    assert "      - name: Complete content preparation checkpoint" not in workflow_text
    assert (
        "python scripts/manage_pipeline_production.py complete "
        "--stage content_preparation"
    ) not in workflow_text
