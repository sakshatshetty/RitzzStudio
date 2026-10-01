import json

import pytest

from modules.topic_intelligence.models import (
    OpportunityCandidate,
    TopicDiscoveryRequest,
)
from scripts import run_approved_content_workflow


@pytest.mark.parametrize("include_request", [True, False])
def test_approved_content_workflow_loads_request_from_discovery_artifact(
    tmp_path,
    monkeypatch,
    capsys,
    include_request,
):
    artifacts_directory = tmp_path / "artifacts"
    artifacts_directory.mkdir()
    candidate = OpportunityCandidate(
        candidate_id="candidate-1",
        topic="Why Did Ancient Cities Rebuild on the Same Ground?",
        provider="vidiq_discovery + gpt_ideation",
    )
    request = TopicDiscoveryRequest(
        niche="RITZZ mixed curiosity explainers",
        mode="EVERGREEN",
        limit=20,
        pipeline_topic_gate=True,
    )
    candidates_payload = {
        "report_id": "report-1",
        "provider": "vidiq_discovery + gpt_ideation",
        "candidates": [candidate.model_dump(mode="json")],
    }
    if include_request:
        candidates_payload["request"] = request.model_dump(mode="json")
    (artifacts_directory / "topic_candidates.json").write_text(
        json.dumps(candidates_payload),
        encoding="utf-8",
    )
    (artifacts_directory / "topic_selection.json").write_text(
        json.dumps({
            "topic": candidate.topic,
            "candidate_id": candidate.candidate_id,
            "target_duration_seconds": 480,
            "minimum_duration_seconds": 480,
            "constraints": [],
        }),
        encoding="utf-8",
    )

    captured = {}

    class FakeContentWorkflow:
        def __init__(self, projects_directory):
            captured["projects_directory"] = projects_directory

        def run(self, **kwargs):
            captured.update(kwargs)
            return type(
                "Result",
                (),
                {
                    "project": type(
                        "Project",
                        (),
                        {
                            "project_id": "project-1",
                            "status": "script_complete",
                        },
                    )(),
                    "project_path": tmp_path / "projects" / "project-1",
                },
            )()

    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(artifacts_directory))
    monkeypatch.setattr(run_approved_content_workflow, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(
        run_approved_content_workflow,
        "ContentWorkflow",
        FakeContentWorkflow,
    )

    assert run_approved_content_workflow.main() == 0
    report = captured["report"]
    if include_request:
        assert report.request == request
        assert "legacy pipeline defaults" not in capsys.readouterr().out
    else:
        assert report.request.niche == "RITZZ mixed curiosity explainers"
        assert report.request.limit == 20
        assert report.request.pipeline_topic_gate is True
        assert "legacy pipeline defaults" in capsys.readouterr().out
    assert report.report_id == "report-1"
    assert report.candidates[0].candidate_id == candidate.candidate_id
    result = json.loads(
        (artifacts_directory / "content_workflow_result.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["topic"] == candidate.topic
    assert result["project_id"] == "project-1"
