import pytest

from modules.topic_intelligence.models import (
    OpportunityCandidate,
    OpportunityReport,
    TopicDiscoveryRequest,
)
from scripts import discover_pipeline_topics
from scripts.discover_pipeline_topics import (
    _candidate_markdown,
    discover_four_candidates,
)


def _candidate(number: int, topic: str) -> OpportunityCandidate:
    return OpportunityCandidate(
        candidate_id=f"candidate-{number}",
        topic=topic,
        provider="vidiq_mcp",
        editorial_status="PASS",
        validation_status="RECOMMENDED",
        ritzz_fit={
            "fit_status": "PASS",
            "fit_score": 80,
            "reason": "Fixture candidate passes.",
        },
    )


def _report(request: TopicDiscoveryRequest, candidates: list[OpportunityCandidate]) -> OpportunityReport:
    return OpportunityReport(
        report_id=f"report-{request.trend_topic or 'all'}",
        request=request,
        provider="vidiq_mcp",
        candidates=candidates,
    )


class SequencedEngine:
    def __init__(self, reports: list[OpportunityReport]):
        self.reports = reports
        self.requests = []

    def discover(self, request: TopicDiscoveryRequest) -> OpportunityReport:
        self.requests.append(request)
        return self.reports[len(self.requests) - 1]


def test_short_category_discovery_backfills_distinct_unscoped_topics():
    request = TopicDiscoveryRequest(mode="TRENDING", trend_topic="history")
    report = _report(
        request,
        [_candidate(number, f"Topic {number}") for number in range(1, 5)],
    )
    report.discovery_diagnostics = {
        "sources_attempted": ["trending", "rising", "evergreen"],
        "source_counts": {
            "trending": {"raw": 2, "unique": 2},
            "rising": {"raw": 6, "unique": 3},
        },
    }
    engine = SequencedEngine([report])

    report, candidates, notes = discover_four_candidates(engine, request)

    assert [candidate.topic for candidate in candidates] == [
        "Topic 1",
        "Topic 2",
        "Topic 3",
        "Topic 4",
    ]
    assert len({candidate.candidate_id for candidate in candidates}) == 4
    assert len(engine.requests) == 1
    assert engine.requests[0].trend_topic == "history"
    assert "rising: raw=6, unique=3" in notes


def test_insufficient_results_after_fallback_reports_clear_error():
    request = TopicDiscoveryRequest(mode="TRENDING", trend_topic="history")
    report = _report(request, [_candidate(1, "Topic One")])
    report.discovery_diagnostics = {
        "sources_attempted": ["trending", "rising", "evergreen", "competitor-outliers", "unscoped-trending"],
        "sources_unavailable": ["evergreen: unsupported"],
        "source_counts": {"trending": {"raw": 1, "unique": 1}},
        "after_inventory_filter": 1,
        "after_niche_filter": 1,
        "after_editorial_filter": 1,
        "after_near_duplicate_filter": 1,
        "final_count": 1,
    }

    with pytest.raises(RuntimeError, match="final eligible distinct candidates") as error:
        discover_four_candidates(SequencedEngine([report]), request)
    assert "evergreen: unsupported" in str(error.value)
    assert "competitor-outliers" in str(error.value)


def test_approval_summary_separates_editorial_fit_from_evidence_status():
    candidate = _candidate(1, "Why do cats purr?")
    candidate.proposed_title = "Why Cats Purr: The Surprising Science"
    candidate.angle = "Explain the biological purpose behind purring."
    candidate.validation_status = "REVIEW"

    summary = _candidate_markdown(1, candidate)

    assert "Why Cats Purr: The Surprising Science" in summary
    assert "Editorial fit: `PASS`" in summary
    assert "Evidence status: `REVIEW`" in summary
    assert "Competitor video performance available: `false`" in summary
    assert "No current demand/trend metric available." in summary


def test_failure_writes_machine_and_human_readable_diagnostics(tmp_path, monkeypatch):
    request = TopicDiscoveryRequest(mode="TRENDING", trend_topic="history")
    report = _report(request, [_candidate(1, "Why do maps show sea monsters?")])
    report.discovery_diagnostics = {
        "request": request.model_dump(mode="json"),
        "sources_attempted": ["trending", "rising", "unscoped-trending"],
        "sources_unavailable": ["evergreen: unsupported"],
        "source_counts": {"trending": {"raw": 8, "unique": 5}},
        "final_count": 1,
        "candidate_exclusions": [{
            "topic": "England vs Spain",
            "sources": ["trending"],
            "ritzz_fit": {"reason": "RITZZ-fit prefilter rejected a live sports matchup."},
        }],
    }

    class OneCandidateEngine:
        def __init__(self, **kwargs):
            pass

        def discover(self, _request):
            return report

    monkeypatch.setattr(discover_pipeline_topics, "TopicIntelligenceEngine", OneCandidateEngine)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setenv("RITZZ_INVENTORY_FILE", str(tmp_path / "inventory.json"))
    monkeypatch.setenv("RITZZ_TREND_TOPIC", "history")
    monkeypatch.setenv("RITZZ_DISCOVERY_MODE", "TRENDING")
    monkeypatch.setenv("RITZZ_DISCOVERY_TIMEFRAME", "this week")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    assert discover_pipeline_topics.main() == 1

    output = tmp_path / "artifacts"
    assert (output / "topic_discovery_diagnostics.json").exists()
    markdown = (output / "topic_discovery_diagnostics.md").read_text()
    assert "evergreen: unsupported" in markdown
    assert "England vs Spain" in markdown
