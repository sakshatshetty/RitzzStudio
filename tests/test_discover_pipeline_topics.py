import json
from pathlib import Path

from modules.topic_intelligence.models import (
    EvidenceMetric,
    OpportunityCandidate,
    OpportunityReport,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.pipeline_topic_discovery import (
    DISCOVERY_MODE,
    PIPELINE_TOPIC_SOURCE,
    VIDIQ_USAGE_MODE,
    TopicDiscoveryFailure,
)
from scripts import discover_pipeline_topics
from scripts.discover_pipeline_topics import _candidate_markdown


def _candidate(index: int) -> OpportunityCandidate:
    source_topic = f"vidIQ topic opportunity {index}"
    return OpportunityCandidate(
        candidate_id=f"candidate-{index}",
        topic=f"Why Did This Ancient Invention Change Everyday Life {index}?",
        proposed_title=f"Why Did This Ancient Invention Change Everyday Life {index}?",
        angle="Explain the problem this unusual invention solved.",
        why_interesting="Its ordinary use concealed an ingenious design.",
        provider=PIPELINE_TOPIC_SOURCE,
        evidence={
            "keyword_score": EvidenceMetric(
                value=90 - index,
                unit="0-100",
                available=True,
                source="vidIQ MCP",
            ),
            "search_volume": EvidenceMetric(
                value=1200,
                unit="monthly searches",
                available=True,
                source="vidIQ MCP",
            ),
        },
        vidiq_status="SCORED",
        inventory_status="ELIGIBLE",
        originality_reason="Focuses on a distinct, practical explanation.",
        raw_evidence={
            "vidiq_opportunity": {
                "topic": source_topic,
                "raw_evidence": {"keyword": source_topic},
            },
            "gpt_generated_idea": {
                "static_visual_explanation": "Draw the device beside a simple cutaway.",
                "long_form_depth": "Explain its origin, operation, and historical impact.",
            },
        },
    )


def _report(candidate_count: int = 5) -> OpportunityReport:
    candidates = [_candidate(index) for index in range(candidate_count)]
    return OpportunityReport(
        report_id="report-1",
        request=TopicDiscoveryRequest(pipeline_topic_gate=True),
        provider=PIPELINE_TOPIC_SOURCE,
        candidates=candidates,
        shortlist_candidate_ids=[candidate.candidate_id for candidate in candidates],
        discovery_diagnostics={
            "status": "SUCCESS",
            "source": PIPELINE_TOPIC_SOURCE,
            "discovery_mode": DISCOVERY_MODE,
            "vidiq_usage_mode": VIDIQ_USAGE_MODE,
            "vidiq_discovery_operation_count": 1,
            "vidiq_opportunities_returned": 20,
            "gpt_calls_made": 1,
            "gpt_ideas_generated": 9,
            "ideas_rejected_count": 2,
            "ideas_rejected": [
                {
                    "title": "The Strange World of Space",
                    "source_opportunity_id": "opp-01",
                    "reason": "Topic is too broad.",
                },
                {
                    "title": "Why Is Celebrity Gossip Everywhere?",
                    "source_opportunity_id": "opp-02",
                    "reason": "Not suitable for RITZZ: celebrity or gossip content.",
                },
            ],
            "final_candidate_count": candidate_count,
        },
    )


def test_candidate_summary_shows_vidiq_to_gpt_provenance():
    summary = _candidate_markdown(1, _candidate(1))

    assert "Why Did This Ancient Invention Change Everyday Life 1?" in summary
    assert "vidIQ opportunity: `vidIQ topic opportunity 1`" in summary
    assert "vidIQ Keyword Score: `89 0-100`" in summary
    assert "Search Volume: `1,200 monthly searches`" in summary
    assert "Originality:" in summary
    assert "RITZZ inventory: `ELIGIBLE`" in summary


def test_main_writes_artifacts_and_candidate_count_for_human_approval(
    tmp_path,
    monkeypatch,
):
    report = _report(5)
    artifact_directory = tmp_path / "artifacts"

    class FixedDiscovery:
        def __init__(self, *_args, **_kwargs):
            self.constructor_args = _args
            self.constructor_kwargs = _kwargs

        def discover(self, _request):
            self.request = _request
            return report

    monkeypatch.setattr(
        discover_pipeline_topics,
        "GPTKeywordTopicDiscovery",
        FixedDiscovery,
    )
    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(artifact_directory))
    monkeypatch.setenv("RITZZ_INVENTORY_FILE", str(tmp_path / "inventory.json"))
    output_path = tmp_path / "github-output.txt"
    summary_path = tmp_path / "github-summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    assert discover_pipeline_topics.main() == 0

    payload = json.loads(
        (artifact_directory / "topic_candidates.json").read_text(encoding="utf-8")
    )
    markdown = (artifact_directory / "topic_candidates.md").read_text(
        encoding="utf-8"
    )
    assert payload["source"] == PIPELINE_TOPIC_SOURCE
    assert payload["discovery_mode"] == "VIDIQ_TO_GPT"
    assert payload["vidiq_usage_mode"] == "DISCOVERY_ONLY"
    assert payload["request"] == report.request.model_dump(mode="json")
    assert len(payload["candidates"]) == 5
    assert [
        candidate["candidate_number"]
        for candidate in payload["candidates"]
    ] == [1, 2, 3, 4, 5]
    assert [f"### {number}." in markdown for number in range(1, 6)] == [True] * 5
    assert "not an automatic selection" in markdown
    assert "VIDIQ_TO_GPT" in markdown
    assert "vidIQ discovery operations: `1`" in markdown
    assert "GPT calls: `1`" in markdown
    assert "## Rejected GPT ideas" in markdown
    assert "The Strange World of Space** — Topic is too broad." in markdown
    assert len(payload["rejected_ideas"]) == 2
    assert "candidate_count=5" in output_path.read_text(encoding="utf-8")
    assert not (artifact_directory / "topic_selection.json").exists()
    assert summary_path.exists()


def test_main_reports_vidiq_provider_error_without_mislabeling_it(tmp_path, monkeypatch):
    failure = TopicDiscoveryFailure({
        "status": "VIDIQ_PROVIDER_ERROR",
        "discovery_mode": DISCOVERY_MODE,
        "vidiq_usage_mode": VIDIQ_USAGE_MODE,
        "vidiq_discovery_operation_count": 1,
        "provider_error": "vidIQ API unavailable",
        "provider_error_type": "INSUFFICIENT_CREDITS",
    })

    class FailedDiscovery:
        def __init__(self, *_args, **_kwargs):
            self.constructor_args = _args
            self.constructor_kwargs = _kwargs

        def discover(self, _request):
            self.request = _request
            raise failure

    monkeypatch.setattr(
        discover_pipeline_topics,
        "GPTKeywordTopicDiscovery",
        FailedDiscovery,
    )
    artifact_directory = tmp_path / "artifacts"
    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(artifact_directory))
    monkeypatch.setenv("RITZZ_INVENTORY_FILE", str(tmp_path / "inventory.json"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert discover_pipeline_topics.main() == 1

    diagnostics = json.loads(
        (artifact_directory / "topic_discovery_diagnostics.json").read_text(
            encoding="utf-8"
        )
    )
    markdown = (artifact_directory / "topic_candidates.md").read_text(
        encoding="utf-8"
    )
    assert diagnostics["status"] == "VIDIQ_PROVIDER_ERROR"
    assert diagnostics["provider_error_type"] == "INSUFFICIENT_CREDITS"
    assert "`VIDIQ_PROVIDER_ERROR`" in markdown
    assert "OPENAI_PROVIDER_ERROR" not in markdown


def test_main_reports_gpt_provider_error(tmp_path, monkeypatch):
    failure = TopicDiscoveryFailure({
        "status": "OPENAI_PROVIDER_ERROR",
        "discovery_mode": DISCOVERY_MODE,
        "vidiq_usage_mode": VIDIQ_USAGE_MODE,
        "vidiq_discovery_operation_count": 1,
        "vidiq_opportunities_returned": 12,
        "gpt_calls_made": 1,
        "provider_error": "GPT unavailable",
    })

    class FailedDiscovery:
        def __init__(self, *_args, **_kwargs):
            self.constructor_args = _args
            self.constructor_kwargs = _kwargs

        def discover(self, _request):
            self.request = _request
            raise failure

    monkeypatch.setattr(
        discover_pipeline_topics,
        "GPTKeywordTopicDiscovery",
        FailedDiscovery,
    )
    artifact_directory = tmp_path / "artifacts"
    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(artifact_directory))
    monkeypatch.setenv("RITZZ_INVENTORY_FILE", str(tmp_path / "inventory.json"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert discover_pipeline_topics.main() == 1
    diagnostics = json.loads(
        (artifact_directory / "topic_discovery_diagnostics.json").read_text(
            encoding="utf-8"
        )
    )
    assert diagnostics["status"] == "OPENAI_PROVIDER_ERROR"


def test_insufficient_qualified_topics_still_write_candidate_diagnostics(
    tmp_path,
    monkeypatch,
):
    report = _report(1)
    report.discovery_diagnostics["status"] = "INSUFFICIENT_QUALIFIED_TOPICS"
    report.discovery_diagnostics["final_candidate_count"] = 1
    artifact_directory = tmp_path / "artifacts"

    class FixedDiscovery:
        def __init__(self, *_args, **_kwargs):
            self.constructor_args = _args
            self.constructor_kwargs = _kwargs

        def discover(self, _request):
            self.request = _request
            return report

    monkeypatch.setattr(
        discover_pipeline_topics,
        "GPTKeywordTopicDiscovery",
        FixedDiscovery,
    )
    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(artifact_directory))
    monkeypatch.setenv("RITZZ_INVENTORY_FILE", str(tmp_path / "inventory.json"))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert discover_pipeline_topics.main() == 1
    diagnostics = json.loads(
        (artifact_directory / "topic_discovery_diagnostics.json").read_text(
            encoding="utf-8"
        )
    )
    assert diagnostics["status"] == "INSUFFICIENT_QUALIFIED_TOPICS"
    assert len(json.loads(
        (artifact_directory / "topic_candidates.json").read_text(encoding="utf-8")
    )["candidates"]) == 1


def test_main_allows_two_candidates_to_proceed_to_human_selection(
    tmp_path,
    monkeypatch,
):
    report = _report(2)
    artifact_directory = tmp_path / "artifacts"

    class FixedDiscovery:
        def __init__(self, *_args, **_kwargs):
            pass

        def discover(self, _request):
            return report

    monkeypatch.setattr(
        discover_pipeline_topics,
        "GPTKeywordTopicDiscovery",
        FixedDiscovery,
    )
    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(artifact_directory))
    monkeypatch.setenv("RITZZ_INVENTORY_FILE", str(tmp_path / "inventory.json"))
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))

    assert discover_pipeline_topics.main() == 0
    assert "candidate_count=2" in output_path.read_text(encoding="utf-8")


def test_workflow_keeps_dynamic_selection_and_m2_behind_human_approval():
    workflow = Path(".github/workflows/ritzz-pipeline.yml").read_text(
        encoding="utf-8"
    )

    assert "candidate_count: ${{ steps.discover.outputs.candidate_count }}" in workflow
    assert "CANDIDATE_COUNT: ${{ steps.candidate-count.outputs.count }}" in workflow
    assert "candidateCount < 2 || candidateCount > 5" in workflow
    assert "Expected 2–5 topic candidates" in workflow
    assert "'/^[1-5]$/ && $0 <= max {" in workflow
    assert "^[1-4]$" not in workflow
    assert "content-preparation:\n    name: Research, outline, and script\n    needs: [test-approval, select-topic, restore-production]" in workflow
    assert "needs.restore-production.outputs.resume_from_index <= 1" in workflow
    assert "Download failed content checkpoint for retry" in workflow
    assert "Upload failed content checkpoint and validation findings" in workflow
    assert 'expected_status == "failed"' in workflow
    assert 'state.get("current_stage") == expected_stage' in workflow
    assert 'bool(expected_stage_state.get("artifacts"))' in workflow
    assert 'tar -xzf "$checkpoint/content-project.tar.gz" -C projects' in workflow
    project_extractions = [
        line.strip()
        for line in workflow.splitlines()
        if "tar -xzf .pipeline-artifacts/" in line
    ]
    assert len(project_extractions) == 10
    assert all("-C projects" in line for line in project_extractions)
    assert "      - name: Install FFmpeg\n        run: |\n          sudo apt-get update\n          sudo apt-get install --yes ffmpeg\n          ffprobe -version" in workflow
    assert "          ffmpeg -version\n          ffprobe -version" in workflow
    assert "      - name: Add review video to artifact root" in workflow
    assert 'cp "$video_file" .pipeline-artifacts/ritzz_test.mp4' in workflow
    assert "open ritzz_test.mp4 from the artifact root" in workflow
    assert "needs: [packaging-approval, render-video, restore-production]" in workflow
    assert "needs.render-video.result == 'success' && format('ritzz-production-{0}-render_video'" in workflow
    assert "needs.render-video.result == 'success' && github.run_id" in workflow
    assert "RITZZ topic approval - production ${process.env.PRODUCTION_ID}" in workflow
    assert "Persist private upload intent before contacting YouTube" in workflow
    assert "      project_id:\n        description: Existing project ID" in workflow
    assert "      rerun_from_stage:" in workflow
    assert "        - private_upload" in workflow
    assert '                      "restart",' in workflow
    assert "rerun-project.tar.gz" in workflow
    assert "Download rerun project" in workflow
    assert "run-id: ${{ needs.render-video.result == 'success' && github.run_id" in workflow
    assert "if: ${{ needs.render-video.result == 'success' || (!endsWith(" in workflow
    assert "Start private-upload stage for rerun or saved-result retry" in workflow
