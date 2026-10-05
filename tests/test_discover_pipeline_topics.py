import pytest

from modules.topic_intelligence.market_intelligence import CompetitorEvidence
from modules.topic_intelligence.models import (
    OpportunityCandidate,
    OpportunityReport,
    TopicDiscoveryRequest,
)
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


def test_pipeline_discovery_uses_only_qualified_competitor_candidates():
    request = TopicDiscoveryRequest(mode="TRENDING", trend_topic="history")
    candidates = [
        _candidate(1, "Topic One"),
        _candidate(2, "Topic Two"),
        _candidate(3, "Topic Three"),
        _candidate(4, "Topic Three"),
        _candidate(5, "Topic Five"),
        _candidate(6, "Topic Six"),
    ]
    candidates[1].editorial_status = "REVIEW"
    candidates[4].validation_status = "REVIEW"
    engine = SequencedEngine(
        [
            _report(request, candidates),
        ]
    )

    report, selected, notes = discover_four_candidates(engine, request)

    assert [candidate.topic for candidate in selected] == [
        "Topic One",
        "Topic Three",
        "Topic Six",
    ]
    assert len({candidate.candidate_id for candidate in selected}) == 3
    assert len(engine.requests) == 1
    assert "no fallback discovery was run" in notes[0]
    assert report.shortlist_candidate_ids == [
        candidate.candidate_id for candidate in selected
    ]


def test_insufficient_competitor_candidates_stop_without_fallback():
    request = TopicDiscoveryRequest(mode="TRENDING", trend_topic="history")
    engine = SequencedEngine(
        [
            _report(
                request,
                [_candidate(1, "Topic One")],
            )
        ]
    )

    with pytest.raises(RuntimeError, match="Only 1 distinct candidates"):
        discover_four_candidates(engine, request)

    assert len(engine.requests) == 1
    assert engine.requests[0].trend_topic == "history"


def test_pipeline_discovery_accepts_two_qualified_competitor_candidates():
    request = TopicDiscoveryRequest(mode="TRENDING", trend_topic="history")
    candidates = [_candidate(1, "Topic One"), _candidate(2, "Topic Two")]
    report = _report(request, candidates)
    engine = SequencedEngine([report])

    result, selected, _ = discover_four_candidates(engine, request)

    assert result is report
    assert [candidate.topic for candidate in selected] == ["Topic One", "Topic Two"]
    assert report.shortlist_candidate_ids == [
        candidate.candidate_id for candidate in candidates
    ]


def test_pipeline_discovery_caps_candidate_choices_at_five():
    request = TopicDiscoveryRequest(mode="TRENDING", trend_topic="history")
    report = _report(
        request,
        [
            _candidate(index, f"Topic {index}")
            for index in range(1, 7)
        ],
    )
    engine = SequencedEngine([report])

    _, selected, _ = discover_four_candidates(engine, request)

    assert len(selected) == 5


def test_approval_summary_separates_editorial_fit_from_evidence_status():
    candidate = _candidate(1, "Why do cats purr?")
    candidate.proposed_title = "Why Cats Purr: The Surprising Science"
    candidate.angle = "Explain the biological purpose behind purring."
    candidate.validation_status = "REVIEW"

    summary = _candidate_markdown(1, candidate)

    assert "Why Cats Purr: The Surprising Science" in summary
    assert "Editorial fit: `PASS`" in summary
    assert "Evidence status: `REVIEW`" in summary


def test_approval_summary_includes_channel_relative_outlier_evidence():
    candidate = _candidate(1, "Why do cats purr?")
    candidate.competitor_evidence = [CompetitorEvidence(
        channel={"name": "Curiosity Channel"},
        video={"title": "Why Cats Purr", "age_days": 12},
        observed_performance={"views": 240_000},
        baseline={"views": 30_000},
        outlier_signal={"ratio": 8.0},
        source="vidIQ MCP",
        collected_at="2026-09-30T00:00:00+00:00",
    )]

    summary = _candidate_markdown(1, candidate)

    assert "channel: Curiosity Channel" in summary
    assert "channel baseline multiple: 8.0x" in summary
    assert "age: 12 days" in summary
