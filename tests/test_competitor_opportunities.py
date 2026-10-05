import json
from types import SimpleNamespace
from typing import Any

from modules.topic_intelligence.competitor_opportunities import (
    CompetitorOpportunityBatch,
    CompetitorOpportunityGenerator,
    CompetitorPatternProposal,
    OriginalTopicProposal,
    candidate_specificity_issue,
)
from modules.topic_intelligence.editorial import (
    CandidateEditorialAssessment,
    EditorialEvaluator,
)
from modules.topic_intelligence.engine import TopicIntelligenceEngine
from modules.topic_intelligence.inventory import (
    ContentInventoryEntry,
    ContentInventoryManager,
    normalize_topic,
)
from modules.topic_intelligence.market_intelligence import (
    CompetitorTopicPattern,
    MarketIntelligenceReport,
    build_market_intelligence_report,
    competitor_evidence_for_video,
    normalize_outlier,
)
from modules.topic_intelligence.models import (
    RITZZ_CHANNEL_NICHE,
    RITZZ_CHANNEL_PROFILE,
    OpportunityCandidate,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.providers.base import (
    ProviderUnavailableError,
    TopicDemandEnrichment,
)
from modules.topic_intelligence.providers.vidiq_mcp import VidiqMcpProvider


class FakeResponses:
    def __init__(self, parsed):
        self.parsed = parsed
        self.inputs = []

    def parse(self, **kwargs):
        self.inputs.append(kwargs)
        return SimpleNamespace(output_parsed=self.parsed)


class FakeGeneratorClient:
    def __init__(self, parsed):
        self.responses = FakeResponses(parsed)


def _video(
    video_id,
    channel_id,
    title,
    *,
    score=None,
    views=1000,
    baseline: int | None = 100,
    group: str | None = None,
):
    record = {
        "videoId": video_id,
        "channelId": channel_id,
        "channelTitle": f"Channel {channel_id}",
        "videoTitle": title,
        "topic": title,
        "viewCount": views,
        "baselineViews": baseline,
        "outlierScore": score,
    }
    if group:
        record["channelGroup"] = group
    return normalize_outlier(record)


def _generation_batch(
    topic="Why Did Humans Stop Sleeping in Two Shifts?",
    *,
    concrete_subject="two shifts",
    subject_evidence_ids=None,
):
    return CompetitorOpportunityBatch(
        patterns=[CompetitorPatternProposal(
            observed_pattern="Historical everyday-life practices reveal how work, light, and social routines shaped sleep.",
            topic_category="history",
            curiosity_type="everyday life",
            core_question="How did historical routines shape human sleep?",
            subject_entities=["preindustrial communities"],
            why_interesting="The pattern links familiar sleep habits to overlooked changes in daily life.",
            evidence_ids=["video-a", "video-b"],
        )],
        opportunities=[OriginalTopicProposal(
            pattern_index=0,
            topic=topic,
            concrete_subject=concrete_subject,
            subject_evidence_ids=(
                subject_evidence_ids
                if subject_evidence_ids is not None
                else ["video-a"]
            ),
            search_concepts=[
                "ancient humans two-shift sleep",
                "prehistoric sleep patterns",
            ],
            angle="Explain how artificial light, work schedules, and changing homes reshaped sleep routines.",
            story_type="HISTORY",
            curiosity_family="history_mystery",
            differentiation_angle="Focus on the historical forces that changed sleep rather than retelling either competitor video.",
            originality_reason="The story explains the documented shift in sleep routines rather than restating either source title.",
            why_interesting="A familiar nightly routine has a surprising history.",
        )],
    )


def test_ritzz_profile_and_gpt_prompts_prioritize_ancient_history():
    profile = RITZZ_CHANNEL_PROFILE.casefold()
    ideation_prompt = CompetitorOpportunityGenerator._system_prompt(10).casefold()
    editorial_prompt = EditorialEvaluator._system_prompt().casefold()

    for focus in (
        "ancient humans",
        "ancient civilizations",
        "ancient human survival",
        "everyday life",
        "ancient technology",
        "ancient history mysteries",
    ):
        assert focus in profile
    assert "ancient-human" in ideation_prompt
    assert "ancient-civilization" in ideation_prompt
    assert "current disasters" in ideation_prompt
    assert "sports" in ideation_prompt
    assert "unrelated general curiosity" in ideation_prompt
    assert "ancient-survival" in editorial_prompt
    assert "current-event disasters" in editorial_prompt


def test_original_topics_require_repeated_success_across_multiple_channels():
    report = MarketIntelligenceReport(
        query="mixed curiosity",
        retrieved_at="2026-09-30T00:00:00+00:00",
        competitor_topic_performance_available=True,
        outliers=[
            _video(
                "video-a",
                "channel-a",
                "Why Ancient People Slept in Two Shifts",
                score=4,
                group="format_competitors",
            ),
            _video(
                "video-b",
                "channel-b",
                "The Strange Way Medieval People Slept",
                score=6,
                group="topic_competitors",
            ),
            _video("video-normal", "channel-c", "A Normal Topic", score=1, baseline=1000),
        ],
    )
    client = FakeGeneratorClient(_generation_batch())
    generator = CompetitorOpportunityGenerator(client=client)

    candidates, patterns, diagnostics = generator.generate(report, candidate_limit=4)

    assert len(candidates) == 1
    assert len(patterns) == 1
    assert patterns[0].channel_count == 2
    assert patterns[0].video_count == 2
    assert patterns[0].channel_groups == [
        "format_competitors",
        "topic_competitors",
    ]
    assert candidates[0].topic == "Why Did Humans Stop Sleeping in Two Shifts?"
    assert candidates[0].ritzz_differentiation_angle
    assert candidates[0].concrete_subject == "two shifts"
    assert candidates[0].subject_evidence_refs == []
    assert candidates[0].originality_reason
    assert len(candidates[0].competitor_evidence) == 2
    assert {
        item.channel_group for item in candidates[0].competitor_evidence
    } == {"format_competitors", "topic_competitors"}
    supplied = json.loads(client.responses.inputs[0]["input"][1]["content"])
    assert {item["evidence_id"] for item in supplied} == {"video-a", "video-b"}
    assert all("tags" in item and "topics" in item for item in supplied)
    assert diagnostics["successful_outlier_videos"] == 2
    assert patterns[0].signal_weight == 1.0
    assert candidates[0].raw_evidence["competitor_signal_weight"] == 1.0


def test_pattern_provenance_is_retained_without_subject_level_citations():
    report = MarketIntelligenceReport(
        query="ancient humans history",
        retrieved_at="2026-09-30T00:00:00+00:00",
        outliers=[
            _video(
                "video-a",
                "channel-a",
                "Why People Slept in Two Shifts",
                score=4,
            ),
            _video(
                "video-b",
                "channel-b",
                "The Strange Way Medieval People Slept",
                score=5,
            ),
            _video(
                "video-c",
                "channel-c",
                "Ancient People Slept in Two Shifts",
                score=6,
            ),
        ],
    )
    batch = _generation_batch(subject_evidence_ids=["video-c"])
    batch.patterns[0].evidence_ids = ["video-a", "video-b"]

    candidates, _, diagnostics = CompetitorOpportunityGenerator(
        client=FakeGeneratorClient(batch)
    ).generate(report)

    assert len(candidates) == 1
    assert candidates[0].subject_evidence_refs == []
    assert candidates[0].raw_evidence["supporting_video_ids"] == [
        "video-a",
        "video-b",
    ]
    assert candidates[0].raw_evidence["vidiq_search_concepts"] == [
        "ancient humans two-shift sleep",
        "prehistoric sleep patterns",
    ]
    assert diagnostics["candidate_rejections"] == []


def test_original_topic_does_not_require_competitor_subject_citation():
    report = MarketIntelligenceReport(
        query="ancient humans history",
        retrieved_at="2026-09-30T00:00:00+00:00",
        outliers=[
            _video("video-a", "channel-a", "Ancient people slept in two shifts", score=4),
            _video("video-b", "channel-b", "Medieval sleep routines", score=5),
        ],
    )
    batch = _generation_batch(
        "Why Did Ancient People Build Cities Underground?",
        concrete_subject="underground cities",
        subject_evidence_ids=["unknown-video"],
    )
    batch.opportunities[0].search_concepts = [
        "ancient underground cities",
        "prehistoric underground homes",
    ]

    candidates, _, diagnostics = CompetitorOpportunityGenerator(
        client=FakeGeneratorClient(batch)
    ).generate(report)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.topic == "Why Did Ancient People Build Cities Underground?"
    assert candidate.concrete_subject == "underground cities"
    assert candidate.subject_evidence_refs == []
    assert candidate.raw_evidence["supporting_video_ids"] == ["video-a", "video-b"]
    assert candidate.raw_evidence["vidiq_search_concepts"] == [
        "ancient underground cities",
        "prehistoric underground homes",
    ]
    assert diagnostics["candidate_rejections"] == []


def test_local_channel_baseline_requires_four_videos_and_uses_three_peers():
    records = [
        {
            "videoId": f"video-{index}",
            "channelId": "channel-a",
            "channelTitle": "Channel A",
            "videoTitle": f"Topic {index}",
            "viewCount": views,
        }
        for index, views in enumerate((1000, 100, 200, 300), start=1)
    ]

    three_video_report = build_market_intelligence_report(
        "history",
        records[:3],
    )
    four_video_report = build_market_intelligence_report(
        "history",
        records,
    )

    assert three_video_report.outliers[0].baseline_views is None
    assert four_video_report.outliers[0].baseline_views == 200
    assert four_video_report.outliers[0].baseline_sample_size == 3
    assert four_video_report.outliers[0].baseline_method == (
        "median of returned same-channel videos"
    )


def test_numeric_string_publish_time_and_video_url_are_kept_as_provenance():
    video = normalize_outlier(
        {
            "videoId": "video-a",
            "videoTitle": "A historical curiosity",
            "videoUrl": "https://example.com/video-a",
            "publishedAt": "1000000000",
        }
    )

    evidence = competitor_evidence_for_video(
        video,
        "fixture",
        "2001-09-19T01:46:40+00:00",
    )

    assert evidence.video["url"] == "https://example.com/video-a"
    assert evidence.video["age_days"] == 10


def test_single_competitor_video_can_seed_a_low_confidence_topic():
    batch = _generation_batch()
    batch.patterns[0].evidence_ids = ["video-a"]
    batch.opportunities[0].subject_evidence_ids = ["video-a"]
    report = MarketIntelligenceReport(
        query="history curiosity",
        retrieved_at="2026-09-30T00:00:00+00:00",
        competitor_topic_performance_available=True,
        outliers=[
            _video(
                "video-a",
                "channel-a",
                "Why Ancient People Slept in Two Shifts",
                score=4,
                group="format_competitors",
            )
        ],
    )

    candidates, patterns, diagnostics = CompetitorOpportunityGenerator(
        client=FakeGeneratorClient(batch)
    ).generate(report)

    assert diagnostics["successful_outlier_videos"] == 1
    assert len(patterns) == 1
    assert patterns[0].confidence == "LOW"
    assert patterns[0].video_count == 1
    assert len(candidates) == 1
    assert candidates[0].competitor_topic_patterns[0].confidence == "LOW"


def test_competitor_title_copy_is_rejected():
    report = MarketIntelligenceReport(
        query="history curiosity",
        retrieved_at="2026-09-30T00:00:00+00:00",
        outliers=[
            _video("video-a", "channel-a", "Why Ancient People Slept in Two Shifts", score=4),
            _video("video-b", "channel-b", "Why Ancient People Slept in Two Shifts", score=5),
        ],
    )
    client = FakeGeneratorClient(
        _generation_batch("Why Ancient People Slept in Two Shifts")
    )

    candidates, _, diagnostics = CompetitorOpportunityGenerator(
        client=client
    ).generate(report)

    assert candidates == []
    assert diagnostics["rejected_copied_angles"] == 1


def test_competitor_title_paraphrase_is_rejected_as_near_duplicate():
    report = MarketIntelligenceReport(
        query="history curiosity",
        retrieved_at="2026-09-30T00:00:00+00:00",
        outliers=[
            _video("video-a", "channel-a", "Why Ancient People Slept in Two Shifts", score=4),
            _video("video-b", "channel-b", "The Strange Way Medieval People Slept", score=5),
        ],
    )
    batch = _generation_batch(
        "Why Ancient People Slept in Two Shifts, Not One",
    )

    candidates, _, diagnostics = CompetitorOpportunityGenerator(
        client=FakeGeneratorClient(batch)
    ).generate(report)

    assert candidates == []
    assert diagnostics["candidate_rejections"][0]["code"] == "NEAR_DUPLICATE"


def test_broad_essay_premise_is_rejected_instead_of_becoming_a_topic():
    report = MarketIntelligenceReport(
        query="history curiosity",
        retrieved_at="2026-09-30T00:00:00+00:00",
        outliers=[
            _video("video-a", "channel-a", "Why Ancient People Slept in Two Shifts", score=4),
            _video("video-b", "channel-b", "The Strange Way Medieval People Slept", score=5),
        ],
    )
    batch = _generation_batch(
        "Why Some Big Questions in History Still Have No Clean Answer"
    )

    candidates, _, diagnostics = CompetitorOpportunityGenerator(
        client=FakeGeneratorClient(batch)
    ).generate(report)

    assert candidates == []
    assert diagnostics["candidate_rejections"][0]["code"] == "TOO_ABSTRACT"
    assert "specific subject" in diagnostics["candidate_rejections"][0]["reason"]


def test_provider_keyword_can_be_refined_before_specificity_is_enforced():
    raw_candidate = OpportunityCandidate(
        candidate_id="keyword-spacex",
        topic="SpaceX",
        proposed_title="SpaceX",
        provider="vidIQ",
        discovery_sources=["trending"],
    )

    assert candidate_specificity_issue(raw_candidate) is None
    assert candidate_specificity_issue(
        raw_candidate,
        final_title=True,
    ) == (
        "TOO_ABSTRACT",
        "Title lacks enough identifying subject detail to distinguish it from a generic essay topic.",
    )

    raw_candidate.proposed_title = "Why Does SpaceX Reuse Its Rockets?"
    assert candidate_specificity_issue(
        raw_candidate,
        final_title=True,
    ) is None


def test_concrete_subject_evidence_matches_terms_across_provider_fields():
    report = MarketIntelligenceReport(
        query="history curiosity",
        retrieved_at="2026-09-30T00:00:00+00:00",
        outliers=[
            _video(
                "video-a",
                "channel-a",
                "A Canal Built Across Central America",
                score=4,
            ),
            _video(
                "video-b",
                "channel-b",
                "Ships Pass Through the Canal",
                score=5,
            ),
        ],
    )
    report.outliers[0].tags = ["Panama"]
    report.outliers[0].topics = ["Canal"]
    batch = _generation_batch(
        "How the Panama Canal Works",
        concrete_subject="Panama Canal",
    )
    client = FakeGeneratorClient(batch)

    candidates, _, diagnostics = CompetitorOpportunityGenerator(
        client=client
    ).generate(report)

    assert len(candidates) == 1
    supplied = json.loads(client.responses.inputs[0]["input"][1]["content"])
    assert supplied[0]["tags"] == ["Panama"]
    assert supplied[0]["topics"] == ["Canal"]
    assert diagnostics["candidate_rejections"] == []


def test_topic_only_and_emerging_signals_receive_lower_weight_than_format():
    generator = CompetitorOpportunityGenerator(client=FakeGeneratorClient(_generation_batch()))

    def extract_weight(group):
        report = MarketIntelligenceReport(
            query="history curiosity",
            retrieved_at="2026-09-30T00:00:00+00:00",
            outliers=[
                _video("video-a", "channel-a", "Why Ancient People Slept in Two Shifts", score=4, group=group),
                _video("video-b", "channel-b", "The Strange Way Medieval People Slept", score=5, group=group),
            ],
        )
        _, patterns, _ = generator.generate(report)
        return patterns[0].signal_weight

    assert extract_weight("format_competitors") == 1.0
    assert extract_weight("emerging_format") == 0.7
    assert extract_weight("topic_competitors") == 0.5


def test_single_channel_pattern_is_retained_with_low_confidence():
    report = MarketIntelligenceReport(
        query="history curiosity",
        retrieved_at="2026-09-30T00:00:00+00:00",
        outliers=[
            _video("video-a", "channel-a", "Why Ancient People Slept in Two Shifts", score=4),
            _video("video-b", "channel-a", "The Strange Way Medieval People Slept", score=5),
        ],
    )

    candidates, patterns, diagnostics = CompetitorOpportunityGenerator(
        client=FakeGeneratorClient(_generation_batch())
    ).generate(report)

    assert len(candidates) == 1
    assert len(patterns) == 1
    assert patterns[0].confidence == "LOW"
    assert patterns[0].channel_count == 1
    assert diagnostics["topic_patterns_extracted"] == 1


def test_missing_success_metrics_do_not_become_outliers_or_generated_ideas():
    report = MarketIntelligenceReport(
        query="history curiosity",
        retrieved_at="2026-09-30T00:00:00+00:00",
        outliers=[
            _video("video-a", "channel-a", "Why Ancient People Slept in Two Shifts", score=None, baseline=None),
            _video("video-b", "channel-b", "The Strange Way Medieval People Slept", score=None, baseline=None),
        ],
    )
    client = FakeGeneratorClient(_generation_batch())

    candidates, patterns, diagnostics = CompetitorOpportunityGenerator(
        client=client
    ).generate(report)

    assert candidates == []
    assert patterns == []
    assert diagnostics["successful_outlier_videos"] == 0
    assert client.responses.inputs == []


def test_above_baseline_but_non_outlier_views_do_not_generate_topics():
    report = MarketIntelligenceReport(
        query="history curiosity",
        retrieved_at="2026-09-30T00:00:00+00:00",
        outliers=[
            _video(
                "video-a",
                "channel-a",
                "Why Ancient People Slept in Two Shifts",
                score=None,
                views=130,
                baseline=100,
            ),
            _video(
                "video-b",
                "channel-b",
                "The Strange Way Medieval People Slept",
                score=None,
                views=150,
                baseline=100,
            ),
        ],
    )
    client = FakeGeneratorClient(_generation_batch())

    candidates, patterns, diagnostics = CompetitorOpportunityGenerator(
        client=client
    ).generate(report)

    assert candidates == []
    assert patterns == []
    assert diagnostics["successful_outlier_videos"] == 0
    assert client.responses.inputs == []


def test_configured_channel_outlier_query_uses_runtime_schema_channel_ids(tmp_path):
    registry = tmp_path / "competitors.json"
    registry.write_text(json.dumps({
        "core": [
            {"channel_id": "channel-a", "name": "Core A", "enabled": True},
            {"channel_id": "channel-disabled", "name": "Disabled", "enabled": False},
        ],
        "adjacent": [{"channel_id": "channel-b", "name": "Adjacent B"}],
        "emerging": [],
    }))

    class ScopedProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture", competitor_registry_path=registry)
            self.calls = []
            self._tools_cache = [{
                "name": "provider_outlier_operation",
                "description": "Find channel videos that outperform their own average.",
                "inputSchema": {
                    "properties": {
                        "channelIds": {"type": "array", "items": {"type": "string"}},
                        "keyword": {"type": "string"},
                        "minOutlierScore": {"type": "number"},
                        "publishedWithin": {
                            "type": "string",
                            "enum": ["thisWeek", "thisMonth", "threeMonths", "sixMonths", "oneYear", "allTime"],
                        },
                        "contentType": {"type": "string", "enum": ["all", "long", "short"]},
                        "sort": {"type": "string", "enum": ["breakoutScore", "publishedAt", "score"]},
                        "limit": {"type": "integer"},
                        "language": {"type": "string", "enum": ["en", "es"]},
                    },
                    "required": [],
                },
            }]

        def _rpc(self, method, params):
            self.calls.append((method, params))
            return {"structuredContent": {"videos": [
                {
                    "videoId": "video-a",
                    "channelId": "channel-a",
                    "videoTitle": "Ancient Sleep Customs",
                    "viewCount": 10000,
                    "averageViews": 1000,
                    "outlierScore": 9,
                },
                {
                    "videoId": "video-b",
                    "channelId": "channel-b",
                    "videoTitle": "Medieval Sleep Habits",
                    "viewCount": 8000,
                    "averageViews": 1000,
                    "outlierScore": 8,
                },
            ]}}

    provider = ScopedProvider()
    report = provider.discover_competitor_research("mixed curiosity", limit=10)

    assert report.configured_competitor_count == 2
    assert report.competitors_queried == 2
    assert report.videos_inspected == 2
    assert [method for method, _ in provider.calls] == ["tools/call", "tools/call"]
    calls = [params for _, params in provider.calls]
    assert [call["arguments"]["channelIds"] for call in calls] == [
        ["channel-a"],
        ["channel-b"],
    ]
    assert all(call["name"] == "provider_outlier_operation" for call in calls)
    assert all("keyword" not in call["arguments"] for call in calls)
    assert all(call["arguments"]["publishedWithin"] == "oneYear" for call in calls)
    assert all(call["arguments"]["minOutlierScore"] == 2 for call in calls)
    assert report.outliers[0].breakout_score == 9
    assert {
        video.video_id: video.channel_group
        for video in report.outliers
    } == {"video-a": "core", "video-b": "adjacent"}


def test_new_competitor_groups_skip_paid_handle_lookups_when_outliers_resolve_references(tmp_path):
    registry = tmp_path / "competitors.json"
    registry.write_text(json.dumps({
        "format_competitors": [{"channel_handle": "@FormatHistory"}],
        "topic_competitors": [{
            "channel_url": "https://www.youtube.com/@TopicHistory"
        }],
        "emerging_format": [{"channel_handle": "@EmergingHistory"}],
    }))

    class GroupedProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture", competitor_registry_path=registry)
            self.calls = []
            self._tools_cache = [
                {
                    "name": "vidiq_channel_search",
                    "inputSchema": {
                        "properties": {
                            "handle": {"type": "string"},
                            "handleMatch": {"type": "string", "enum": ["exact", "fuzzy"]},
                            "limit": {"type": "integer"},
                        },
                    },
                },
                {
                    "name": "vidiq_outliers",
                    "description": "Find breakout and overperforming videos",
                    "inputSchema": {
                        "properties": {
                            "channelIds": {
                                "type": "array",
                                "maxItems": 50,
                                "description": "Channel IDs, handles, or channel URLs.",
                                "items": {"type": "string"},
                            },
                            "limit": {"type": "integer"},
                        },
                        "required": ["channelIds"],
                    },
                },
            ]
            self.channel_ids = {
                "@FormatHistory": "UC-format",
                "https://www.youtube.com/@TopicHistory": "UC-topic",
                "@EmergingHistory": "UC-emerging",
            }

        def _rpc(self, method, params):
            self.calls.append(params)
            if params["name"] == "vidiq_channel_search":
                reference = params["arguments"]["handle"]
                channel_id = self.channel_ids[reference]
                return {"structuredContent": {"channels": [{
                    "channelId": channel_id,
                    "channelTitle": f"Verified {reference}",
                    "handle": reference,
                    "description": "History explainers",
                    "channelType": "long",
                    "faceless": True,
                }]}}
            reference = params["arguments"]["channelIds"][0]
            channel_id = self.channel_ids[reference]
            return {"structuredContent": {"videos": [{
                "videoId": f"video-{channel_id}",
                "channelId": channel_id,
                "videoTitle": f"Why {channel_id} changed history",
                "viewCount": 10000,
                "breakoutScore": 90,
            }]}}

    provider = GroupedProvider()
    report = provider.discover_competitor_research("history", limit=10)

    assert [call["name"] for call in provider.calls] == ["vidiq_outliers"] * 3
    assert {
        video.channel_id: video.channel_group
        for video in report.outliers
    } == {
        "UC-format": "format_competitors",
        "UC-topic": "topic_competitors",
        "UC-emerging": "emerging_format",
    }
    assert all(
        channel["metadata_status"] == "provider_resolves_reference"
        for channel in report.channels
    )
    assert report.competitor_group_diagnostics == {
        "format_competitors": {
            "configured": 1,
            "resolved": 1,
            "queried": 1,
            "researched": 1,
            "videos_inspected": 1,
            "successful_outliers": 1,
        },
        "topic_competitors": {
            "configured": 1,
            "resolved": 1,
            "queried": 1,
            "researched": 1,
            "videos_inspected": 1,
            "successful_outliers": 1,
        },
        "emerging_format": {
            "configured": 1,
            "resolved": 1,
            "queried": 1,
            "researched": 1,
            "videos_inspected": 1,
            "successful_outliers": 1,
        },
    }


def test_handle_is_passed_to_outlier_tool_when_metadata_lookup_is_unavailable(tmp_path):
    registry = tmp_path / "competitors.json"
    registry.write_text(json.dumps({
        "format_competitors": [{"channel_handle": "@FormatHistory"}],
        "topic_competitors": [],
        "emerging_format": [],
    }))

    class HandleProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture", competitor_registry_path=registry)
            self.calls = []
            self._tools_cache = [{
                "name": "vidiq_outliers",
                "description": "Find breakout videos",
                "inputSchema": {
                    "properties": {
                        "channelIds": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer"},
                    },
                    "required": ["channelIds"],
                },
            }]

        def _rpc(self, method, params):
            self.calls.append(params)
            return {"structuredContent": {"videos": []}}

    provider = HandleProvider()
    report = provider.discover_competitor_research("history", limit=5)

    assert provider.calls[0]["arguments"]["channelIds"] == ["@FormatHistory"]
    assert report.competitor_group_diagnostics["format_competitors"]["queried"] == 1
    assert report.competitor_group_diagnostics["format_competitors"]["researched"] == 1
    assert report.competitor_group_diagnostics["format_competitors"]["resolved"] == 1
    assert report.channels[0]["metadata_status"] == "not_available"


def test_empty_competitor_registry_does_not_substitute_unscoped_ideas(tmp_path):
    registry = tmp_path / "competitors.json"
    registry.write_text(json.dumps({"core": [], "adjacent": [], "emerging": []}))

    class NoCompetitorsProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture", competitor_registry_path=registry)
            self.calls = []
            self._tools_cache = [{
                "name": "vidiq_outliers",
                "description": "Outlier video research",
                "inputSchema": {"properties": {"channelIds": {"type": "array"}}},
            }]

        def _rpc(self, method, params):
            self.calls.append((method, params))
            return {}

    provider = NoCompetitorsProvider()
    report = provider.discover_competitor_research("mixed curiosity")

    assert report.configured_competitor_count == 0
    assert report.outliers == []
    assert report.operations[0]["error_type"] == "NO_COMPETITORS_CONFIGURED"
    assert provider.calls == []


def test_channel_video_fallback_supplies_metrics_for_title_only_outlier_results(tmp_path):
    registry = tmp_path / "competitors.json"
    registry.write_text(json.dumps({
        "core": [{"channel_id": "channel-a", "name": "Channel A"}],
        "adjacent": [],
        "emerging": [],
    }))

    class ChannelVideoFallbackProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture", competitor_registry_path=registry)
            self.calls = []
            self._tools_cache = [
                {
                    "name": "vidiq_outliers",
                    "description": "Channel-scoped outlier video research",
                    "inputSchema": {
                        "properties": {
                            "channelId": {"type": "string"},
                        },
                        "required": ["channelId"],
                    },
                },
                {
                    "name": "vidiq_channel_videos",
                    "description": "List recent and popular channel videos",
                    "inputSchema": {
                        "properties": {
                            "channelId": {"type": "string"},
                            "videoFormat": {"type": "string", "enum": ["long"]},
                            "popular": {"type": "boolean"},
                        },
                        "required": ["channelId", "videoFormat", "popular"],
                    },
                },
            ]

        def _rpc(self, method, params):
            self.calls.append((method, params))
            if params["name"] == "vidiq_outliers":
                return {"structuredContent": {"videos": [{
                    "videoId": "video-a",
                    "channelId": "channel-a",
                    "videoTitle": "A history of sleep",
                }]}}
            return {"structuredContent": {"videos": [{
                "videoId": "video-a",
                "channelId": "channel-a",
                "viewCount": 500,
                "baselineViews": 100,
            }]}}

    provider = ChannelVideoFallbackProvider()
    report = provider.discover_competitor_research("history explainers")

    assert report.competitor_topic_performance_available is True
    assert report.outliers[0].views == 500
    assert report.outliers[0].relative_performance == 5
    assert report.outliers[0].channel_group == "core"
    assert [call[1]["name"] for call in provider.calls] == [
        "vidiq_outliers",
        "vidiq_channel_videos",
        "vidiq_channel_videos",
    ]


def test_insufficient_outlier_credits_block_paid_channel_video_fallback(tmp_path):
    registry = tmp_path / "competitors.json"
    registry.write_text(json.dumps({
        "format_competitors": [{"channel_handle": "@FormatHistory"}],
        "topic_competitors": [{"channel_handle": "@TopicHistory"}],
        "emerging_format": [],
    }))

    class CreditLimitedProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture", competitor_registry_path=registry)
            self.calls = []
            self._tools_cache = [
                {
                    "name": "vidiq_outliers",
                    "description": "Channel-scoped outlier video research",
                    "inputSchema": {
                        "properties": {
                            "channelIds": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["channelIds"],
                    },
                },
                {
                    "name": "vidiq_channel_videos",
                    "description": "List recent and popular channel videos",
                    "inputSchema": {
                        "properties": {
                            "channelId": {"type": "string"},
                            "videoFormat": {"type": "string", "enum": ["long"]},
                            "popular": {"type": "boolean"},
                        },
                        "required": ["channelId", "videoFormat", "popular"],
                    },
                },
            ]

        def _rpc(self, _method, params):
            assert _method == "tools/call"
            self.calls.append(params["name"])
            raise ProviderUnavailableError(
                "vidIQ reports insufficient credits.",
                error_type="INSUFFICIENT_CREDITS",
            )

    provider = CreditLimitedProvider()
    report = provider.discover_competitor_research("history", limit=5)

    assert provider.calls == ["vidiq_outliers"]
    assert any(
        operation["error_type"] == "INSUFFICIENT_CREDITS"
        and operation["status"] == "blocked"
        for operation in report.operations
    )
    assert report.competitor_group_diagnostics["topic_competitors"]["queried"] == 0


def test_keyword_provider_error_is_optional_for_competitor_candidate_generation(tmp_path):
    report = build_market_intelligence_report(
        "mixed curiosity",
        [
            {
                "videoId": "video-a",
                "channelId": "channel-a",
                "channelTitle": "Channel A",
                "videoTitle": "Why Ancient People Slept in Two Shifts",
                "viewCount": 1000,
                "baselineViews": 100,
                "outlierScore": 8,
            },
            {
                "videoId": "video-b",
                "channelId": "channel-b",
                "channelTitle": "Channel B",
                "videoTitle": "The Strange Way Medieval People Slept",
                "viewCount": 900,
                "baselineViews": 100,
                "outlierScore": 7,
            },
        ],
    )
    report.configured_competitor_count = 2
    report.competitors_queried = 2

    class CompetitorProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture")

        def discover_competitor_research(
            self,
            query: str,
            limit: int = 10,
        ) -> MarketIntelligenceReport:
            _ = (query, limit)
            return report

        def enrich_topic_demand(self, topic: str) -> TopicDemandEnrichment:
            _ = topic
            raise ProviderUnavailableError(
                "vidIQ keyword research is temporarily unavailable.",
                error_type="TOOL_TIMEOUT",
                tool="vidiq_keyword_research",
            )

        def discover_pipeline_candidates(
            self,
            _request: TopicDiscoveryRequest,
            *,
            include_competitor_research: bool = True,
        ) -> tuple[
            list[OpportunityCandidate],
            dict[str, Any],
            MarketIntelligenceReport | None,
        ]:
            _ = (_request, include_competitor_research)
            return [], {
                "source_counts": {},
                "sources_unavailable": [],
                "operations": [],
                "stage_counts": [],
            }, None

    class Generator(CompetitorOpportunityGenerator):
        model_name = "fixture-generator"

        def __init__(self):
            pass

        def generate(
            self,
            _report: MarketIntelligenceReport,
            *,
            candidate_limit: int = 8,
        ) -> tuple[
            list[OpportunityCandidate],
            list[CompetitorTopicPattern],
            dict[str, Any],
        ]:
            _ = (_report, candidate_limit)
            candidate = OpportunityCandidate(
                candidate_id="generated-1",
                topic="Why Did Humans Stop Sleeping in Two Shifts?",
                provider="vidIQ MCP competitor research",
                discovery_sources=["competitor-topic-pattern"],
                ritzz_differentiation_angle="Explain the historical shift in sleep routines.",
                observed_pattern="Historical changes reshaped everyday sleep routines.",
                concrete_subject="two shifts",
                subject_evidence_refs=["video-a"],
                originality_reason="Explain why sleep schedules changed rather than reciting source titles.",
                curiosity_family="history_mystery",
                raw_evidence={
                    "subject_evidence": [{
                        "evidence_id": "video-a",
                        "title": report.outliers[0].title,
                        "topic": report.outliers[0].topic,
                        "tags": report.outliers[0].tags,
                        "topics": report.outliers[0].topics,
                    }],
                },
                competitor_evidence=[
                    competitor_evidence_for_video(
                        report.outliers[0],
                        "vidIQ MCP competitor outliers",
                        report.retrieved_at,
                    )
                ],
            )
            pattern = CompetitorTopicPattern(
                topic="How did past routines shape sleep?",
                video_count=2,
                channel_count=2,
                channels=["Channel A", "Channel B"],
                video_ids=["video-a", "video-b"],
            )
            candidate.competitor_topic_patterns = [pattern]
            return [candidate], [pattern], {
                "videos_inspected": 2,
                "successful_outlier_videos": 2,
                "topic_patterns_extracted": 1,
                "generated_candidates": 1,
                "rejected_copied_angles": 0,
            }

    class Editorial(EditorialEvaluator):
        model_name = "fixture"
        prompt_version = "fixture-v1"

        def __init__(self):
            pass

        def assess(
            self,
            candidates: list[OpportunityCandidate],
        ) -> list[CandidateEditorialAssessment]:
            return [CandidateEditorialAssessment(
                candidate_id=item.candidate_id,
                audience_fit=90,
                curiosity=90,
                evergreen=90,
                visual=90,
                format_fit=90,
                researchability=90,
                differentiation=90,
                saturation=80,
                story_depth=90,
                originality=90,
                story_type="HISTORY",
                status="PASS",
            ) for item in candidates]

    result = TopicIntelligenceEngine(
        provider=CompetitorProvider(),
        cache_dir=tmp_path,
        editorial_evaluator=Editorial(),
        competitor_opportunity_generator=Generator(),
    ).discover(TopicDiscoveryRequest(pipeline_topic_gate=False))

    assert result.candidates[0].topic == "Why Did Humans Stop Sleeping in Two Shifts?"
    assert result.candidates[0].ritzz_fit is not None
    assert result.candidates[0].ritzz_fit.fit_status == "PASS"
    assert result.candidates[0].current_vidiq_demand_available is False
    assessment = result.candidates[0].competition_saturation_assessment
    assert assessment is not None
    assert "Current vidIQ competition signal unavailable." in assessment
    operations = result.discovery_diagnostics.get("operations")
    sources_unavailable = result.discovery_diagnostics.get("sources_unavailable")
    assert isinstance(operations, list)
    assert isinstance(sources_unavailable, list)
    assert any(
        operation["source"] == "keyword_research_enrichment"
        and operation["error_type"] == "PROVIDER_ERROR"
        for operation in operations
    )
    assert any(
        item.startswith("keyword_research_enrichment: PROVIDER_ERROR")
        for item in sources_unavailable
    )


def test_pipeline_discovery_runs_competitors_ideation_and_vidiq_without_fallback(
    tmp_path,
):
    competitor_report = MarketIntelligenceReport(
        query="ancient humans ancient civilizations",
        retrieved_at="2026-09-30T00:00:00+00:00",
        outliers=[
            _video(
                f"video-{index}",
                f"channel-{index}",
                title,
                score=8,
            )
            for index, title in enumerate(
                (
                    "How Ancient Humans Survived Freezing Winters",
                    "How Ancient Cities Brought Water to Their People",
                    "What Ancient Families Ate Every Day",
                ),
                start=1,
            )
        ],
    )
    candidates = [
        OpportunityCandidate(
            candidate_id=f"idea-{index}",
            topic=topic,
            provider="vidiq_mcp",
            discovery_sources=["configured_competitor_outliers"],
            raw_evidence={"vidiq_search_concepts": concepts},
        )
        for index, (topic, *concepts) in enumerate(
            (
                (
                    "How Did Ancient Humans Stay Warm in Winter?",
                    "ancient humans winter survival",
                    "prehistoric humans winter",
                    "ancient human cold survival",
                ),
                ("How Did Ancient Cities Get Clean Water?", "ancient city water supply"),
                ("What Did Ancient Families Eat Every Day?", "ancient humans daily food"),
                ("How Did Ancient Engineers Move Water Uphill?", "ancient engineering water lift"),
                ("What Happened to the Ancient Army That Vanished?", "vanished roman legion"),
                ("Why Did a Nepal Flood Become Deadly So Fast?", "recent Nepal flood"),
                ("What Happened in Yesterday's Championship Final?", "championship result today"),
                ("Why Are Clouds Different Shapes?", "cloud shapes"),
            ),
            start=1,
        )
    ]

    class Provider:
        name = "vidiq_mcp"

        def __init__(self):
            self.validation_topics = []
            self.competitor_queries = []

        def discover(
            self,
            request: TopicDiscoveryRequest,
        ) -> list[OpportunityCandidate]:
            raise AssertionError("General topic discovery must not be called.")

        def discover_competitor_research(self, query, limit=10):
            assert limit > 0
            self.competitor_queries.append(query)
            return competitor_report

        def enrich_topic_demand(self, topic):
            self.validation_topics.append(topic)
            if topic == "cloud shapes":
                return {
                    "available": False,
                    "metrics": {},
                    "related_keywords": [],
                    "query": topic,
                    "raw_response": {"records": []},
                    "operation": {
                        "source": "keyword_research_enrichment",
                        "tool": "fixture",
                        "status": "valid_zero_results",
                        "message": "No relevant keyword evidence was returned.",
                        "query": topic,
                        "call_made": "true",
                    },
                }
            concept_record = {
                "ancient humans winter survival": "prehistoric winter survival",
                "ancient city water supply": "ancient city water",
                "ancient humans daily food": "prehistoric human food",
                "ancient engineering water lift": "ancient water engineering",
                "vanished roman legion": "lost Roman legion",
                "recent Nepal flood": "Nepal flood",
                "championship result today": "championship",
                "cloud shapes": "clouds",
            }[topic]
            return {
                "available": True,
                "metrics": {
                    "search_volume": {
                        "value": 100,
                        "unit": "monthly searches",
                        "available": True,
                        "source": "fixture",
                    }
                },
                "related_keywords": [],
                "query": topic,
                "raw_response": {
                    "records": [
                        {
                            "keyword": concept_record,
                            "search_volume": 100,
                        }
                    ]
                },
                "operation": {
                    "source": "keyword_research_enrichment",
                    "tool": "fixture",
                    "status": "success",
                    "query": topic,
                    "call_made": "true",
                },
            }

    class Generator(CompetitorOpportunityGenerator):
        def generate(
            self,
            report: MarketIntelligenceReport,
            *,
            candidate_limit: int = 8,
        ) -> tuple[
            list[OpportunityCandidate],
            list[CompetitorTopicPattern],
            dict[str, Any],
        ]:
            assert candidate_limit >= 3
            return candidates, [], {
                "successful_outlier_videos": 3,
                "generated_candidates": 8,
            }

    class Editorial:
        def assess(
            self,
            candidates: list[OpportunityCandidate],
        ) -> list[CandidateEditorialAssessment]:
            return [
                CandidateEditorialAssessment(
                    candidate_id=candidate.candidate_id,
                    audience_fit=90,
                    curiosity=90,
                    evergreen=90,
                    visual=90,
                    researchability=90,
                    differentiation=90,
                    saturation=90,
                    format_fit=90,
                    story_depth=90,
                    originality=90,
                    status=(
                        "PASS"
                        if candidate.candidate_id in {
                            "idea-1",
                            "idea-2",
                            "idea-3",
                            "idea-4",
                            "idea-5",
                        }
                        else "REVIEW"
                    ),
                )
                for candidate in candidates
            ]

    provider = Provider()
    result = TopicIntelligenceEngine(
        provider=provider,
        cache_dir=tmp_path,
        editorial_evaluator=Editorial(),
        competitor_opportunity_generator=Generator(),
    ).discover(TopicDiscoveryRequest(pipeline_topic_gate=True, force_refresh=True))

    assert len(result.candidates) == 5
    assert len(provider.validation_topics) == 8
    assert provider.validation_topics == [
        "ancient humans winter survival",
        "ancient city water supply",
        "ancient humans daily food",
        "ancient engineering water lift",
        "vanished roman legion",
        "recent Nepal flood",
        "championship result today",
        "cloud shapes",
    ]
    assert provider.competitor_queries == [
        f"{RITZZ_CHANNEL_NICHE} curiosity explainer format competitors"
    ]
    assert {item.topic for item in result.candidates} == {
        "How Did Ancient Humans Stay Warm in Winter?",
        "How Did Ancient Cities Get Clean Water?",
        "What Did Ancient Families Eat Every Day?",
        "How Did Ancient Engineers Move Water Uphill?",
        "What Happened to the Ancient Army That Vanished?",
    }
    assert result.discovery_diagnostics["gpt_ideation_calls"] == 1
    assert result.discovery_diagnostics["vidiq_validation_calls"] == 8
    assert result.discovery_diagnostics["fallback_discovery_calls"] == 0
    assert result.discovery_diagnostics["recommendation_gate"]["qualified_candidates"] == 5
    assert result.discovery_diagnostics["status"] == "SUCCESS"
    assert len(result.discovery_diagnostics["candidate_validation"]) == 8
    first_validation = result.discovery_diagnostics["candidate_validation"][0]
    assert first_validation["topic"] == "How Did Ancient Humans Stay Warm in Winter?"
    assert first_validation["search_concepts"] == [
        "ancient humans winter survival",
        "prehistoric humans winter",
        "ancient human cold survival",
    ]
    assert first_validation["vidiq_query"] == "ancient humans winter survival"
    assert first_validation["raw_vidiq_response"]["records"][0]["keyword"] == (
        "prehistoric winter survival"
    )
    assert first_validation["normalized_vidiq_evidence"]["search_volume"]["value"] == 100
    assert first_validation["validation_result"] == "PASS"
    current_event_validation = next(
        item
        for item in result.discovery_diagnostics["candidate_validation"]
        if item["topic"] == "Why Did a Nepal Flood Become Deadly So Fast?"
    )
    assert current_event_validation["validation_result"] == "PASS"
    assert current_event_validation["vidiq_query"] == "recent Nepal flood"
    assert current_event_validation["final_validation_result"] == "FAIL"
    assert current_event_validation["final_rejection_reason"]
    assert "Why Did a Nepal Flood Become Deadly So Fast?" not in {
        item.topic for item in result.candidates
    }
    assert result.discovery_diagnostics["vidiq_validated_ideas"] == 7
    failed_validation = next(
        item
        for item in result.discovery_diagnostics["candidate_validation"]
        if item["vidiq_query"] == "cloud shapes"
    )
    assert failed_validation["validation_result"] == "FAIL"
    assert failed_validation["rejection_reason"] == (
        "No relevant keyword evidence was returned."
    )
    assert failed_validation["raw_vidiq_response"] == {"records": []}


def test_new_subjects_reach_vidiq_with_pattern_provenance_and_inventory_filter(
    tmp_path,
):
    topics = [
        (
            "Why Did Ancient People Build Cities Underground?",
            "underground cities",
            ["ancient underground cities", "prehistoric underground homes"],
        ),
        (
            "How Did Ancient Engineers Move Water Without Pumps?",
            "ancient water engineering",
            ["ancient water engineering", "ancient water lifting"],
        ),
        (
            "How Did Ancient People Preserve Food for Winter?",
            "ancient food preservation",
            ["ancient food preservation", "prehistoric food storage"],
        ),
    ]
    report = MarketIntelligenceReport(
        query="ancient history curiosity",
        retrieved_at="2026-10-05T00:00:00+00:00",
        outliers=[
            _video(
                "video-jungle",
                "channel-jungle",
                "What's Hidden Under the Jungles of New Guinea?",
                score=8,
            ),
            _video(
                "video-ruins",
                "channel-ruins",
                "A Lost City Buried Beneath an Ancient Forest",
                score=7,
            ),
        ],
    )
    batch = _generation_batch(
        topics[0][0],
        concrete_subject=topics[0][1],
        subject_evidence_ids=[],
    )
    batch.patterns[0].observed_pattern = (
        "Successful videos create curiosity about hidden archaeological places."
    )
    batch.patterns[0].topic_category = "archaeological discovery"
    batch.patterns[0].curiosity_type = "hidden places"
    batch.patterns[0].core_question = (
        "What evidence and places remain hidden beneath familiar landscapes?"
    )
    batch.patterns[0].evidence_ids = ["video-jungle", "video-ruins"]
    first_idea = batch.opportunities[0].model_copy(update={
        "search_concepts": topics[0][2],
        "angle": "Explain why some ancient communities chose underground city layouts.",
        "originality_reason": (
            "The new topic investigates ancient urban design rather than a hidden jungle discovery."
        ),
        "subject_evidence_ids": [],
    })
    additional_ideas = [
        first_idea.model_copy(update={
            "topic": topic,
            "concrete_subject": subject,
            "search_concepts": concepts,
            "angle": f"Explain the historical problem behind {subject}.",
            "originality_reason": (
                f"This topic explores {subject}, distinct from the competitor videos' "
                "hidden archaeological discoveries."
            ),
            "subject_evidence_ids": [],
        })
        for topic, subject, concepts in topics[1:]
    ]
    batch.opportunities = [first_idea, *additional_ideas]

    class Provider:
        name = "vidiq_mcp"

        def __init__(self):
            self.validation_queries: list[str] = []

        def discover(self, request: TopicDiscoveryRequest) -> list[OpportunityCandidate]:
            raise AssertionError("General discovery and fallback sources must not run.")

        def discover_competitor_research(self, query, limit=10):
            assert limit >= 2
            return report

        def enrich_topic_demand(self, topic: str) -> TopicDemandEnrichment:
            self.validation_queries.append(topic)
            return {
                "available": True,
                "metrics": {
                    "search_volume": {
                        "value": 100,
                        "unit": "monthly searches",
                        "available": True,
                        "source": "mock_vidiq",
                    }
                },
                "related_keywords": [topic],
                "query": topic,
                "raw_response": {
                    "records": [{"keyword": topic, "search_volume": 100}]
                },
                "operation": {
                    "source": "keyword_research_enrichment",
                    "tool": "mock_vidiq",
                    "status": "success",
                    "query": topic,
                    "call_made": "true",
                },
            }

    class Editorial(EditorialEvaluator):
        model_name = "fixture"
        prompt_version = "fixture-v1"

        def __init__(self):
            pass

        def assess(
            self,
            candidates: list[OpportunityCandidate],
        ) -> list[CandidateEditorialAssessment]:
            return [
                CandidateEditorialAssessment(
                    candidate_id=candidate.candidate_id,
                    audience_fit=90,
                    curiosity=90,
                    evergreen=90,
                    visual=90,
                    format_fit=90,
                    researchability=90,
                    differentiation=90,
                    saturation=80,
                    story_depth=90,
                    originality=90,
                    story_type="HISTORY",
                    status="PASS",
                )
                for candidate in candidates
            ]

    inventory_manager = ContentInventoryManager(tmp_path / "inventory.json")
    inventory_manager.add(ContentInventoryEntry(
        topic=topics[0][0],
        normalized_topic=normalize_topic(topics[0][0]),
    ))
    provider = Provider()
    result = TopicIntelligenceEngine(
        provider=provider,
        cache_dir=tmp_path,
        inventory_manager=inventory_manager,
        editorial_evaluator=Editorial(),
        competitor_opportunity_generator=CompetitorOpportunityGenerator(
            client=FakeGeneratorClient(batch)
        ),
    ).discover(TopicDiscoveryRequest(
        pipeline_topic_gate=True,
        force_refresh=True,
    ))

    assert result.discovery_diagnostics["gpt_ideas_generated"] == 3
    assert result.discovery_diagnostics["gpt_candidates_grounded"] == 3
    assert provider.validation_queries == [topics[1][2][0], topics[2][2][0]]
    assert result.discovery_diagnostics["vidiq_validation_calls"] == 2
    assert result.discovery_diagnostics["vidiq_validated_ideas"] == 2
    assert result.discovery_diagnostics["fallback_discovery_calls"] == 0
    assert len(result.candidates) == 2
    assert {candidate.topic for candidate in result.candidates} == {
        topics[1][0],
        topics[2][0],
    }
    validations = result.discovery_diagnostics["candidate_validation"]
    inventory_rejection = next(
        item for item in validations if item["topic"] == topics[0][0]
    )
    assert inventory_rejection["rejection_reason"] == (
        "Overlaps existing RITZZ content inventory."
    )
    assert inventory_rejection["vidiq_result"] == "NOT_RUN"
    assert inventory_rejection["final_validation_result"] == "FAIL"
    for topic in topics[1:]:
        validation = next(item for item in validations if item["topic"] == topic[0])
        assert validation["vidiq_result"] == "PASS"
        assert validation["originality_result"] == "PASS"
        assert validation["final_validation_result"] == "PASS"
        assert validation["underlying_pattern"]["core_question"] == (
            batch.patterns[0].core_question
        )
        assert validation["competitor_inspiration"]
        assert {
            source["title"] for source in validation["competitor_inspiration"]
        } == {
            "What's Hidden Under the Jungles of New Guinea?",
            "A Lost City Buried Beneath an Ancient Forest",
        }
