import pytest

from modules.topic_intelligence.models import (
    OpportunityCandidate,
    OpportunityReport,
    TopicDiscoveryRequest,
)
from scripts.discover_pipeline_topics import discover_four_candidates


def _candidate(number: int, topic: str) -> OpportunityCandidate:
    return OpportunityCandidate(
        candidate_id=f"candidate-{number}",
        topic=topic,
        provider="vidiq_mcp",
        validation_status="RECOMMENDED",
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
    category_candidates = [_candidate(1, "Topic One"), _candidate(2, "Topic Two")]
    category_candidates[1].validation_status = "REVIEW"
    category_report = _report(request, category_candidates)
    broader_request = request.model_copy(update={"trend_topic": None, "force_refresh": True})
    broader_report = _report(
        broader_request,
        [
            _candidate(2, "Topic Two"),
            _candidate(3, "Topic Three"),
            _candidate(4, "Topic Four"),
            _candidate(1, "Topic Five"),
        ],
    )
    engine = SequencedEngine([category_report, broader_report])

    report, candidates, notes = discover_four_candidates(engine, request)

    assert [candidate.topic for candidate in candidates] == [
        "Topic One",
        "Topic Two",
        "Topic Three",
        "Topic Four",
    ]
    assert len({candidate.candidate_id for candidate in candidates}) == 4
    assert len(engine.requests) == 2
    assert engine.requests[1].trend_topic is None
    assert report.warnings[0].startswith("The 'history' category")
    assert "unscoped fallback" in notes[1]


def test_insufficient_results_after_fallback_reports_clear_error():
    request = TopicDiscoveryRequest(mode="TRENDING", trend_topic="history")
    category_report = _report(request, [_candidate(1, "Topic One")])
    broader_request = request.model_copy(update={"trend_topic": None, "force_refresh": True})
    broader_report = _report(broader_request, [_candidate(2, "Topic Two")])

    with pytest.raises(RuntimeError, match="only 2 distinct candidates after fallback"):
        discover_four_candidates(SequencedEngine([category_report, broader_report]), request)
