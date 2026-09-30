import json
from typing import ClassVar

import pytest
import requests

from modules.topic_intelligence.editorial import (
    CandidateEditorialAssessment,
    CandidateEditorialAssessments,
    EditorialEvaluator,
    apply_editorial_assessments,
)
from modules.topic_intelligence.engine import TopicIntelligenceEngine
from modules.topic_intelligence.evaluator import rank_candidates, score_candidate
from modules.topic_intelligence.inventory import (
    ContentInventoryEntry,
    ContentInventoryManager,
    normalize_topic,
)
from modules.topic_intelligence.market_intelligence import (
    build_market_intelligence_report,
    normalize_outlier,
    relevant_competitor_evidence,
    top_outliers,
)
from modules.topic_intelligence.models import (
    EvidenceMetric,
    OpportunityCandidate,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.providers.base import ProviderUnavailableError
from modules.topic_intelligence.providers.vidiq_mcp import VidiqMcpProvider
from modules.topic_intelligence.ritzz_fit import (
    build_ritzz_fit_result,
    prefilter_reason,
)
from modules.topic_intelligence.validation import validate_candidates


class FakeResponse:
    status_code = 200
    headers: ClassVar = {"Mcp-Session-Id": "session-1"}

    def __init__(self, payload):
        self.payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self.payload


class FakeMcpSession:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(kwargs)
        body = kwargs["json"]
        if body["method"] == "initialize":
            return FakeResponse({"jsonrpc": "2.0", "id": body["id"], "result": {"capabilities": {}}})
        if body["method"] == "notifications/initialized":
            return FakeResponse({})
        if body["method"] == "tools/list":
            return FakeResponse({"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [{
                "name": "rising_keywords",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            }]}})
        return FakeResponse({"jsonrpc": "2.0", "id": body["id"], "result": {"structuredContent": {"keywords": [{"keyword": "Why do birds migrate?", "search_volume": 1200}]}}})


def test_provider_outlier_research_uses_supported_vidiq_arguments():
    session = FakeMcpSession()
    provider = VidiqMcpProvider(api_key="test-key", session=session)
    original_post = session.post

    def post(url, **kwargs):
        session.calls.append(kwargs)
        body = kwargs["json"]
        if body["method"] == "tools/list":
            return FakeResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": {"tools": [{
                "name": "vidiq_outliers",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string"},
                        "contentType": {"type": "string"},
                        "sort": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["keyword", "contentType", "sort", "limit"],
                },
            }]}})
        if body["method"] == "tools/call":
            return FakeResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": {"structuredContent": {
                "videos": [{"videoId": "abc", "videoTitle": "A mystery", "viewCount": 123}]
            }}})
        if body["method"] == "initialize":
            return FakeResponse({"jsonrpc": "2.0", "id": body.get("id"), "result": {"capabilities": {}}})
        return original_post(url, **kwargs)

    session.post = post
    report = provider.discover_outliers("history mysteries", limit=3)
    call = next(item for item in session.calls if item["json"].get("method") == "tools/call")
    assert call["json"]["params"]["name"] == "vidiq_outliers"
    assert call["json"]["params"]["arguments"] == {
        "keyword": "history mysteries", "contentType": "long", "sort": "score", "limit": 3,
    }
    assert report.outliers[0].title == "A mystery"


def test_provider_collects_channels_and_video_performance_when_capabilities_exist():
    class MockedVidiqProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture")
            self.calls = []
            self.tools = [
                {
                    "name": "vidiq_similar_channels",
                    "inputSchema": {
                        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                        "required": ["query", "limit"],
                    },
                },
                {
                    "name": "vidiq_outliers",
                    "inputSchema": {
                        "properties": {
                            "keyword": {"type": "string"},
                            "contentType": {"type": "string"},
                            "sort": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["keyword", "contentType", "sort", "limit"],
                    },
                },
            ]

        def _rpc(self, method, params):
            if method == "tools/list":
                return {"tools": self.tools}
            self.calls.append(params)
            if params["name"] == "vidiq_similar_channels":
                return {"structuredContent": {"channels": [{
                    "channelId": "channel-1",
                    "channelTitle": "Cat Science",
                    "subscriberCount": 12000,
                }]}}
            return {"structuredContent": {"videos": [{
                "videoId": "video-1",
                "videoTitle": "Why Cats Purr",
                "channelId": "channel-1",
                "viewCount": 800,
                "baselineViews": 100,
            }]}}

    provider = MockedVidiqProvider()
    report = provider.discover_competitor_research("cat curiosity", limit=5)

    assert report.competitor_topic_performance_available is True
    assert report.channels[0]["name"] == "Cat Science"
    assert report.outliers[0].relative_performance == 8
    assert [call["name"] for call in provider.calls] == [
        "vidiq_similar_channels",
        "vidiq_outliers",
    ]


def test_competitor_video_with_strong_channel_relative_outlier():
    report = build_market_intelligence_report(
        "cat curiosity",
        [
            {
                "videoId": "video-1",
                "videoTitle": "Why Cats Purr",
                "channelId": "channel-1",
                "channelTitle": "Cat Science",
                "viewCount": 1000,
            },
            {
                "videoId": "video-2",
                "videoTitle": "How Cats Communicate",
                "channelId": "channel-1",
                "channelTitle": "Cat Science",
                "viewCount": 100,
            },
            {
                "videoId": "video-3",
                "videoTitle": "Why Cats Knead",
                "channelId": "channel-1",
                "channelTitle": "Cat Science",
                "viewCount": 120,
            },
        ],
    )

    item = next(video for video in report.outliers if video.video_id == "video-1")
    assert report.competitor_topic_performance_available is True
    assert item.relative_performance == 1000 / 110
    assert item.outlier_signal == "strong_outlier"
    evidence = relevant_competitor_evidence("Why do cats purr?", report)[0]
    assert evidence.channel["name"] == "Cat Science"
    assert evidence.video["title"] == "Why Cats Purr"
    assert evidence.baseline["views"] == 110
    assert evidence.baseline["sample_size"] == 2
    assert evidence.outlier_signal["metric"] == "video_views / competitor_channel_baseline_views"


def test_competitor_video_below_strong_outlier_threshold_is_not_labeled_outlier():
    report = build_market_intelligence_report(
        "birds",
        [{
            "videoId": "video-1",
            "videoTitle": "How Birds Migrate",
            "channelId": "channel-1",
            "viewCount": 130,
            "baselineViews": 100,
        }],
    )

    assert report.outliers[0].outlier_signal == "above_baseline"
    assert report.outliers[0].relative_performance == 1.3


def test_competitor_topics_repeated_across_channels_are_summarized():
    report = build_market_intelligence_report(
        "ancient engineering",
        [
            {
                "videoId": "video-1",
                "videoTitle": "How Ancient Engineers Moved Stone",
                "videoTopics": ["Ancient Engineering"],
                "channelId": "channel-1",
                "channelTitle": "History Lab",
                "viewCount": 900,
                "breakoutScore": 72,
            },
            {
                "videoId": "video-2",
                "videoTitle": "Ancient Engineering Explained",
                "videoTopics": ["Ancient Engineering"],
                "channelId": "channel-2",
                "channelTitle": "Curiosity Works",
                "viewCount": 800,
                "breakoutScore": 68,
            },
        ],
    )

    assert len(report.topic_patterns) == 1
    assert report.topic_patterns[0].video_count == 2
    assert report.topic_patterns[0].channel_count == 2


def test_raw_views_alone_do_not_create_successful_topic_patterns():
    report = build_market_intelligence_report(
        "space",
        [
            {
                "videoId": "video-1",
                "videoTitle": "A mystery in space",
                "videoTopics": ["space mysteries"],
                "channelId": "channel-1",
                "viewCount": 1_000_000,
            },
            {
                "videoId": "video-2",
                "videoTitle": "Another mystery in space",
                "videoTopics": ["space mysteries"],
                "channelId": "channel-2",
                "viewCount": 900_000,
            },
        ],
    )

    assert report.topic_patterns == []


def test_missing_competitor_metrics_remain_unavailable():
    report = build_market_intelligence_report(
        "space",
        [{
            "videoId": "video-1",
            "videoTitle": "A mystery in space",
            "channelId": "channel-1",
        }],
    )

    assert report.competitor_topic_performance_available is False
    assert report.outliers[0].views is None
    assert report.outliers[0].relative_performance is None
    assert any("no usable performance metrics" in warning for warning in report.warnings)


def test_provider_records_unavailable_competitor_video_capability():
    class MockedVidiqProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture")
            self.methods = []

        def _rpc(self, method, params):
            self.methods.append((method, params))
            return {"tools": [{"name": "rising_keywords"}]} if method == "tools/list" else {}

    provider = MockedVidiqProvider()
    report = provider.discover_competitor_research("mixed curiosity", limit=10)

    assert report.competitor_topic_performance_available is False
    assert report.outliers == []
    assert any("does not advertise the vidiq_outliers" in warning for warning in report.warnings)
    assert [method for method, _ in provider.methods] == ["tools/list"]


def test_pipeline_discovery_uses_ordered_multi_source_fallbacks():
    class MockedVidiqProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture")
            self.calls = []
            self.tools = [
                {
                    "name": "trending_videos",
                    "inputSchema": {
                        "properties": {
                            "topic": {"type": "string"},
                            "timeframe": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["topic"],
                    },
                },
                {
                    "name": "rising_keywords",
                    "inputSchema": {
                        "properties": {
                            "keyword": {"type": "string"},
                            "mode": {"type": "string", "enum": ["rising"]},
                            "limit": {"type": "integer"},
                        },
                        "required": ["keyword", "mode"],
                    },
                },
                {
                    "name": "keyword_research",
                    "description": "Research related keywords",
                    "inputSchema": {
                        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "vidiq_similar_channels",
                    "inputSchema": {
                        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "vidiq_outliers",
                    "inputSchema": {
                        "properties": {
                            "keyword": {"type": "string"},
                            "contentType": {"type": "string"},
                            "sort": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["keyword", "contentType", "sort", "limit"],
                    },
                },
            ]

        def _rpc(self, method, params):
            if method == "tools/list":
                return {"tools": self.tools}
            name = params["name"]
            arguments = params["arguments"]
            self.calls.append((name, arguments))
            if name == "trending_videos":
                label = "History weekly mystery" if arguments.get("timeframe") == "this week" else "History monthly discovery"
                return {"structuredContent": {"topics": [{"topic": label}]}}
            if name == "rising_keywords":
                raise ProviderUnavailableError("rising tool timed out")
            if name == "keyword_research":
                return {"structuredContent": {"keywords": [
                    {"keyword": "Why do ancient maps show sea monsters?"},
                    {"keyword": "How did Roman concrete last so long?"},
                ]}}
            if name == "vidiq_similar_channels":
                return {"structuredContent": {"channels": [{"channelId": "channel-1", "channelTitle": "History Lab"}]}}
            if name == "vidiq_outliers":
                return {"structuredContent": {"videos": [{
                    "videoId": "video-1",
                    "videoTitle": "How Romans Built Roads",
                    "videoTopics": ["Roman road engineering"],
                    "channelId": "channel-1",
                    "viewCount": 500,
                    "baselineViews": 100,
                }]}}
            raise AssertionError(name)

    provider = MockedVidiqProvider()
    candidates, diagnostics, competitor_report = provider.discover_pipeline_candidates(
        TopicDiscoveryRequest(
            mode="TRENDING",
            timeframe="this week",
            trend_topic="history",
            limit=10,
            pipeline_topic_gate=True,
        )
    )

    assert diagnostics["sources_attempted"] == [
        "trending",
        "broader-trending",
        "rising",
        "evergreen",
        "long-tail",
        "competitor-outliers",
        "unscoped-trending",
    ]
    assert diagnostics["sources_unavailable"] == [
        "rising: rising tool timed out",
        "long-tail: no supported vidIQ tool advertised",
    ]
    assert diagnostics["source_counts"]["evergreen"]["unique"] == 2
    assert diagnostics["source_counts"]["long-tail"] == {"raw": 0, "unique": 0}
    assert any(item.discovery_sources == ["competitor-outliers"] for item in candidates)
    assert competitor_report is not None
    assert competitor_report.outliers[0].topic == "Roman road engineering"
    assert provider.calls[0][1]["topic"] == "history"
    assert provider.calls[1][1]["timeframe"] == "this month"
    assert "topic" not in provider.calls[-1][1]


def test_pipeline_discovery_can_backfill_a_small_trending_pool_from_rising_keywords():
    class RisingProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture")
            self.tools = [
                {
                    "name": "trending_videos",
                    "inputSchema": {
                        "properties": {"topic": {"type": "string"}, "limit": {"type": "integer"}},
                        "required": ["topic"],
                    },
                },
                {
                    "name": "rising_keywords",
                    "inputSchema": {
                        "properties": {
                            "keyword": {"type": "string"},
                            "mode": {"type": "string", "enum": ["rising"]},
                            "limit": {"type": "integer"},
                        },
                        "required": ["keyword", "mode"],
                    },
                },
            ]

        def _rpc(self, method, params):
            if method == "tools/list":
                return {"tools": self.tools}
            if params["name"] == "trending_videos":
                return {"structuredContent": {"topics": [{"topic": "History's lost inventions"}]}}
            if params["name"] == "rising_keywords":
                return {"structuredContent": {"keywords": [
                    {"keyword": "Why did ancient cities build underground tunnels?"},
                    {"keyword": "How did sailors navigate before GPS?"},
                    {"keyword": "Why are old maps full of sea monsters?"},
                    {"keyword": "How did ancient people make purple dye?"},
                ]}}
            raise AssertionError(params["name"])

    provider = RisingProvider()
    candidates, diagnostics, _ = provider.discover_pipeline_candidates(
        TopicDiscoveryRequest(
            mode="TRENDING",
            trend_topic="history",
            timeframe="this week",
            pipeline_topic_gate=True,
        )
    )

    assert diagnostics["source_counts"]["trending"]["raw"] == 1
    assert diagnostics["source_counts"]["rising"]["unique"] == 4
    assert len(candidates) >= 4
    assert all("rising" in item.discovery_sources for item in candidates if item.topic.startswith("Why") or item.topic.startswith("How"))

    rising_only_provider = RisingProvider()
    rising_only_provider.tools = rising_only_provider.tools[1:]
    rising_only_candidates, rising_only_diagnostics, _ = (
        rising_only_provider.discover_pipeline_candidates(
            TopicDiscoveryRequest(
                mode="TRENDING",
                trend_topic="history",
                timeframe="this week",
                pipeline_topic_gate=True,
            )
        )
    )
    assert rising_only_diagnostics["source_counts"]["trending"] == {"raw": 0, "unique": 0}
    assert len(rising_only_candidates) == 4
    assert all(item.discovery_sources == ["rising"] for item in rising_only_candidates)


def test_long_tail_source_is_used_only_when_advertised():
    class LongTailProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture")
            self.tools = [{
                "name": "long_tail_keywords",
                "description": "Discover long-tail keyword questions",
                "inputSchema": {
                    "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                    "required": ["query"],
                },
            }]

        def _rpc(self, method, params):
            if method == "tools/list":
                return {"tools": self.tools}
            return {"structuredContent": {"keywords": [
                {"keyword": "Why did medieval builders use flying buttresses?"},
                {"keyword": "How did ancient sailors navigate by stars?"},
            ]}}

    provider = LongTailProvider()
    candidates, diagnostics, _ = provider.discover_pipeline_candidates(
        TopicDiscoveryRequest(mode="EVERGREEN", limit=15)
    )

    assert diagnostics["provider_capabilities"]["long_tail"] is True
    assert diagnostics["source_counts"]["long-tail"]["unique"] == 2
    assert all("long-tail" in item.discovery_sources for item in candidates)


def test_provider_related_question_is_a_separate_story_candidate_not_a_rewritten_trend():
    class RelatedQuestionProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture")
            self.tools = [{
                "name": "trending_videos",
                "inputSchema": {
                    "properties": {"topic": {"type": "string"}, "limit": {"type": "integer"}},
                    "required": ["topic"],
                },
            }]

        def _rpc(self, method, params):
            if method == "tools/list":
                return {"tools": self.tools}
            return {"structuredContent": {"topics": [{
                "topic": "England vs Spain",
                "relatedQuestions": [
                    "Why did England and Spain become football rivals?"
                ],
            }]}}

    candidates, _, _ = RelatedQuestionProvider().discover_pipeline_candidates(
        TopicDiscoveryRequest(
            mode="TRENDING",
            trend_topic="history",
            timeframe="this week",
            limit=15,
        )
    )
    story_candidate = next(
        item for item in candidates
        if item.topic.startswith("Why did England")
    )

    assert story_candidate.discovery_sources == ["trending-related-question"]
    assert story_candidate.raw_evidence["related_to"] == "England vs Spain"
    assert story_candidate.topic != "England vs Spain"


def test_configured_competitor_registry_scopes_queries_and_preserves_group(tmp_path):
    registry_path = tmp_path / "competitors.json"
    registry_path.write_text(json.dumps({
        "core": [{"channel_id": "core-1", "name": "Core Example"}],
        "adjacent": [{"handle": "@adjacent", "name": "Adjacent Example"}],
        "emerging": [],
    }))

    class ScopedProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="fixture", competitor_registry_path=registry_path)
            self.calls = []

        def _rpc(self, method, params):
            if method == "tools/list":
                return {"tools": [{
                    "name": "vidiq_outliers",
                    "inputSchema": {
                        "properties": {
                            "keyword": {"type": "string"},
                            "channelId": {"type": "string"},
                            "contentType": {"type": "string"},
                            "sort": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["keyword", "channelId", "contentType", "sort", "limit"],
                    },
                }]}
            self.calls.append(params["arguments"])
            channel_id = params["arguments"]["channelId"]
            return {"structuredContent": {"videos": [{
                "videoId": f"video-{channel_id}",
                "videoTitle": f"Why {channel_id} matters",
                "topic": "historical engineering",
                "viewCount": 200,
                "baselineViews": 100,
            }]}}

    provider = ScopedProvider()
    report = provider.discover_competitor_research("history explainers", limit=5)

    assert [call["channelId"] for call in provider.calls] == ["core-1", "@adjacent"]
    assert {item.channel_group for item in report.outliers} == {"core", "adjacent"}


def candidate(topic, *, keyword_score=None, search_volume=None, competition=None, growth=None):
    evidence = {}
    if keyword_score is not None:
        evidence["keyword_score"] = EvidenceMetric(
            value=keyword_score, unit="0-100", available=True, source="fixture"
        )
    if search_volume is not None:
        evidence["search_volume"] = EvidenceMetric(value=search_volume, available=True, source="fixture")
    if competition is not None:
        evidence["competition"] = EvidenceMetric(value=competition, available=True, source="fixture")
    if growth is not None:
        evidence["growth"] = EvidenceMetric(value=growth, available=True, source="fixture")
    return OpportunityCandidate(candidate_id=topic, topic=topic, provider="fixture", evidence=evidence)


def test_scoring_keeps_unavailable_values_missing():
    item = candidate("A topic")
    item.evidence["search_volume_score"] = EvidenceMetric(value=75, unit="0-100", available=True, source="fixture")
    result = score_candidate(item)
    assert result.component_scores["demand"] == 75
    assert result.component_scores["momentum"] is None
    assert result.score_completeness < 1
    assert "Momentum evidence unavailable" in result.rationale


def test_numeric_competition_is_converted_to_opportunity_score():
    result = rank_candidates([candidate("Topic", search_volume=100, competition=59.5)])[0]
    assert result.component_scores["competition"] == 40.5


def test_ranking_is_deterministic_and_prefers_evidenced_score():
    items = [candidate("Zebra topic"), candidate("High topic", search_volume=8000), candidate("Low topic", search_volume=20)]
    ranked = rank_candidates(items)
    assert [item.topic for item in ranked] == ["High topic", "Low topic", "Zebra topic"]
    assert ranked[-1].opportunity_score is None


def test_inventory_normalizes_and_finds_near_duplicate_topics(tmp_path):
    manager = ContentInventoryManager(tmp_path / "content_inventory.json")
    manager.add(ContentInventoryEntry(
        topic="Why Do Cats Purr?",
        normalized_topic=normalize_topic("Why Do Cats Purr?"),
        project_id="p1",
    ))
    assert manager.find_overlap("Why do cats purr")
    assert not manager.find_overlap("Why do owls hunt at night")


def test_engine_returns_at_most_four_distinct_candidates(tmp_path):
    class ManyProvider:
        name = "fixture"

        def discover(self, request):
            return [candidate(f"Topic {index}", search_volume=100 - index) for index in range(6)]

    report = TopicIntelligenceEngine(
        provider=ManyProvider(),
        cache_dir=tmp_path,
        editorial_evaluator=FakeEditorialEvaluator(),
    ).discover()
    assert len(report.candidates) == 4
    assert len({item.topic for item in report.candidates}) == 4


def test_niche_filter_flags_broad_and_unsuitable_topics():
    items = [
        candidate("United Nations"),
        candidate("Celebrity gossip"),
        candidate("Paradise movie review"),
        candidate("Why do birds migrate?"),
    ]
    from modules.topic_intelligence.validation import apply_niche_filter

    apply_niche_filter(items)

    assert items[0].filter_reasons
    assert items[1].filter_reasons
    assert items[2].filter_reasons
    assert items[3].filter_reasons == []


def test_pipeline_topic_gate_keeps_editorial_pass_even_if_metrics_need_review(tmp_path):
    class ManyProvider:
        name = "fixture"

        def discover(self, request):
            return [
                candidate("Paradise movie review", search_volume=100),
                candidate("United Nations", search_volume=90),
                candidate("Why do cats purr?", search_volume=80),
                candidate("Why do birds migrate?", search_volume=70),
                candidate("How do bats navigate?", search_volume=60),
                candidate("Why do volcanoes erupt?", search_volume=50),
            ]

    report = TopicIntelligenceEngine(
        provider=ManyProvider(),
        cache_dir=tmp_path,
        editorial_evaluator=FakeEditorialEvaluator(),
    ).discover(TopicDiscoveryRequest(pipeline_topic_gate=True))

    assert len(report.candidates) == 4
    assert all(item.editorial_status == "PASS" for item in report.candidates)
    assert all("review" not in item.topic.casefold() for item in report.candidates)
    assert all(item.topic != "United Nations" for item in report.candidates)


def test_editorial_information_is_not_treated_as_a_filter_reason():
    item = candidate("Chaos Canyon secret badge")
    assessment = CandidateEditorialAssessment(
        candidate_id=item.candidate_id,
        audience_fit=85,
        curiosity=82,
        evergreen=70,
        visual=80,
        researchability=75,
        differentiation=70,
        saturation=65,
        status="PASS",
        rationale=["None significant from the supplied data."],
        filter_reasons=["None significant from the supplied data."],
    )

    apply_editorial_assessments([item], [assessment])

    assert item.editorial_status == "PASS"
    assert item.rationale == ["None significant from the supplied data."]
    assert item.filter_reasons == []


def test_validation_rejects_matchups_in_reverse_order_and_related_pirate_topics():
    matchups = [
        candidate("England vs Spain"),
        candidate("Spain vs England"),
    ]
    related = [
        candidate("Why do pirates wear eye patches?"),
        candidate("Why did sailors use eye patches?"),
    ]
    for item in matchups + related:
        item.opportunity_score = 75
        item.score_completeness = 1

    validate_candidates(matchups)
    validate_candidates(related)

    assert matchups[0].validation_status == "RECOMMENDED"
    assert matchups[1].validation_status == "REVIEW"
    assert any("near-duplicate" in reason.casefold() for reason in matchups[1].validation_reasons)
    assert related[0].validation_status == "RECOMMENDED"
    assert related[1].validation_status == "REVIEW"
    assert any("near-duplicate" in reason.casefold() for reason in related[1].validation_reasons)


def test_pipeline_discovery_reports_candidate_stage_counts_and_keeps_exactly_four(tmp_path):
    class PipelineProvider(FakeProvider):
        def discover_pipeline_candidates(self, request):
            items = [
                candidate(f"Curiosity question {index}", search_volume=100 - index)
                for index in range(6)
            ]
            for item in items:
                item.discovery_sources = ["rising"]
            return items, {
                "pool_target": request.limit,
                "sources_attempted": ["trending", "rising", "evergreen"],
                "sources_unavailable": ["evergreen: tool unavailable"],
                "source_counts": {
                    "trending": {"raw": 2, "unique": 2},
                    "rising": {"raw": 6, "unique": 4},
                    "evergreen": {"raw": 0, "unique": 0},
                },
                "stage_counts": [
                    {"stage": "trending", "raw_total": 2, "pool_unique_total": 2},
                    {"stage": "rising", "raw_total": 6, "pool_unique_total": 6},
                ],
            }, None

    report = TopicIntelligenceEngine(
        provider=PipelineProvider(),
        cache_dir=tmp_path,
        editorial_evaluator=FakeEditorialEvaluator(),
    ).discover(TopicDiscoveryRequest(pipeline_topic_gate=True))

    assert len(report.candidates) == 4
    assert report.discovery_diagnostics["raw_candidates"] == 6
    assert report.discovery_diagnostics["after_editorial_filter"] == 6
    assert report.discovery_diagnostics["after_near_duplicate_filter"] == 6
    assert report.discovery_diagnostics["final_count"] == 4
    assert report.discovery_diagnostics["source_counts"]["rising"]["unique"] == 4
    assert report.discovery_diagnostics["sources_unavailable"] == [
        "evergreen: tool unavailable"
    ]


def test_pipeline_does_not_promote_editorial_review_or_fail_candidates(tmp_path):
    class MixedEditorialEvaluator(FakeEditorialEvaluator):
        def assess(self, candidates):
            statuses = {
                "Strong explainer topic": "PASS",
                "Under-specified topic": "REVIEW",
                "Movie recap": "FAIL",
            }
            return [
                CandidateEditorialAssessment(
                    candidate_id=item.candidate_id,
                    audience_fit=80,
                    curiosity=80,
                    evergreen=80,
                    visual=80,
                    researchability=80,
                    differentiation=80,
                    saturation=80,
                    status=statuses[item.topic],
                    rationale=[],
                )
                for item in candidates
            ]

    class ManyProvider(FakeProvider):
        def discover_pipeline_candidates(self, request):
            return [
                candidate(topic, search_volume=100)
                for topic in ("Strong explainer topic", "Under-specified topic", "Movie recap")
            ], {"source_counts": {"trending": {"raw": 3, "unique": 3}}}, None

    report = TopicIntelligenceEngine(
        provider=ManyProvider(),
        cache_dir=tmp_path,
        editorial_evaluator=MixedEditorialEvaluator(),
    ).discover(TopicDiscoveryRequest(pipeline_topic_gate=True))

    assert [item.topic for item in report.candidates] == ["Strong explainer topic"]
    assert report.candidates[0].editorial_status == "PASS"
    exclusions = {item["topic"]: item["editorial_status"] for item in report.discovery_diagnostics["candidate_exclusions"]}
    assert exclusions["Under-specified topic"] == "REVIEW"
    assert exclusions["Movie recap"] == "FAIL"


def test_ritzz_fit_prefilter_rejects_fixtures_and_ambiguous_entities():
    assert prefilter_reason(candidate("England vs Spain"))[0] == "FAIL"
    assert prefilter_reason(candidate("Udta Teer trailer"))[0] == "FAIL"
    assert prefilter_reason(candidate("Bruno PH"))[0] == "REVIEW"
    assert prefilter_reason(candidate("Ashke"))[0] == "REVIEW"
    assert prefilter_reason(candidate("Why do birds migrate?")) is None


def test_ritzz_fit_pass_requires_editorial_pass_and_configured_score():
    item = candidate("Why do ancient maps show sea monsters?")
    assessment = build_ritzz_fit_result(
        item,
        story_type="MYSTERY",
        editorial_status="PASS",
        editorial_scores={
            "curiosity": 90,
            "researchability": 80,
            "visual": 75,
            "evergreen": 80,
            "audience_fit": 85,
        },
    )
    low_score = build_ritzz_fit_result(
        item,
        editorial_status="PASS",
        editorial_scores={
            "curiosity": 50,
            "researchability": 50,
            "visual": 50,
            "evergreen": 50,
            "audience_fit": 50,
        },
    )
    editorial_review = build_ritzz_fit_result(
        item,
        editorial_status="REVIEW",
        editorial_scores={"curiosity": 100},
    )

    assert assessment.fit_status == "PASS"
    assert assessment.story_type == "MYSTERY"
    assert low_score.fit_status == "REVIEW"
    assert editorial_review.fit_status == "REVIEW"


def test_competitor_evidence_cannot_override_ritzz_fit_fail(tmp_path):
    class ProviderWithStrongCompetitorEvidence(FakeProvider):
        def discover(self, request):
            return [candidate("England vs Spain", search_volume=1000)]

        def discover_competitor_research(self, query, limit=10):
            return build_market_intelligence_report(
                query,
                [{
                    "videoId": "outlier",
                    "videoTitle": "England vs Spain",
                    "topic": "England vs Spain",
                    "channelId": "channel",
                    "viewCount": 10000,
                    "baselineViews": 100,
                }],
            )

    report = TopicIntelligenceEngine(
        provider=ProviderWithStrongCompetitorEvidence(),
        cache_dir=tmp_path,
        editorial_evaluator=FakeEditorialEvaluator(),
    ).discover(TopicDiscoveryRequest(pipeline_topic_gate=True))

    assert report.candidates == []
    exclusion = report.discovery_diagnostics["candidate_exclusions"][0]
    assert exclusion["ritzz_fit"]["fit_status"] == "FAIL"
    assert "matchup" in exclusion["ritzz_fit"]["reason"]


def test_pipeline_does_not_lower_evidence_gate_to_reach_four(tmp_path):
    class UnscoredProvider(FakeProvider):
        def discover(self, request):
            return [candidate("Why do ancient maps show sea monsters?")]

    class LowEditorialScore(FakeEditorialEvaluator):
        def assess(self, candidates):
            return [
                CandidateEditorialAssessment(
                    candidate_id=item.candidate_id,
                    audience_fit=20,
                    curiosity=20,
                    evergreen=20,
                    visual=20,
                    researchability=20,
                    differentiation=20,
                    saturation=20,
                    status="PASS",
                )
                for item in candidates
            ]

    report = TopicIntelligenceEngine(
        provider=UnscoredProvider(),
        cache_dir=tmp_path,
        editorial_evaluator=LowEditorialScore(),
    ).discover(TopicDiscoveryRequest(pipeline_topic_gate=True))

    assert report.candidates == []
    exclusion = report.discovery_diagnostics["candidate_exclusions"][0]
    assert exclusion["validation_status"] == "REVIEW"
    assert any("Opportunity score" in item for item in exclusion["validation_reasons"])


def test_engine_attaches_competitor_report_when_provider_supports_it(tmp_path):
    class ProviderWithMarket(FakeProvider):
        def discover_outliers(self, query, limit=10):
            return type("Market", (), {"model_dump": lambda self: {"query": query, "outliers": []}})()

    report = TopicIntelligenceEngine(
        provider=ProviderWithMarket(),
        cache_dir=tmp_path,
        editorial_evaluator=FakeEditorialEvaluator(),
    ).discover()

    assert report.competitor_report == {
        "query": "mixed curiosity explainers curiosity explainers",
        "outliers": [],
    }


def test_growth_without_demand_does_not_receive_momentum_score():
    items = rank_candidates([candidate("Tiny base", growth=900), candidate("Known demand", search_volume=100)])
    tiny = next(item for item in items if item.topic == "Tiny base")
    assert tiny.component_scores["momentum"] is None


def test_huge_growth_on_below_median_demand_does_not_win_ranking():
    items = rank_candidates([
        candidate("Tiny demand, huge spike", search_volume=10, growth=10000),
        candidate("Established demand", search_volume=100000, growth=5),
    ])
    assert items[0].topic == "Established demand"
    assert items[1].component_scores["momentum"] is None


def test_provider_arguments_follow_discovered_schema():
    tool = {
        "name": "keyword_research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "timeframe": {"type": "string", "enum": ["today", "this_week"]},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
    }
    args = VidiqMcpProvider._arguments(tool, TopicDiscoveryRequest(timeframe="this week", limit=7))
    assert args["query"] == "mixed curiosity explainers YouTube topic opportunities"
    assert args["timeframe"] == "this_week"
    assert args["limit"] == 7


def test_provider_maps_vidiq_keyword_research_to_rising_mode_and_period():
    tool = {
        "name": "vidiq_keyword_research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["research", "questions", "rising"]},
                "period": {"type": "string", "enum": ["day", "week", "month"]},
                "keyword": {"type": "string"},
                "topic": {"type": "string"},
                "limit": {"type": "integer"},
                "language": {"type": "string", "enum": ["all", "en", "ru"]},
            },
            "required": ["mode"],
        },
    }
    args = VidiqMcpProvider._arguments(
        tool,
        TopicDiscoveryRequest(timeframe="this week", trend_topic="history"),
    )
    assert args == {"mode": "rising", "period": "week", "topic": "history", "limit": 10, "language": "en"}
    assert "keyword" not in args


def test_provider_leaves_rising_topic_unscoped_when_none_is_selected():
    tool = {
        "name": "vidiq_keyword_research",
        "inputSchema": {
            "type": "object",
            "properties": {"topic": {"type": "string"}},
        },
    }
    assert VidiqMcpProvider._arguments(tool, TopicDiscoveryRequest()) == {}


def test_provider_argument_mapping_uses_field_names_and_schema_types():
    tool = {
        "name": "keyword_research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "A keyword with number of results"},
                "country": {"type": "string", "description": "Country to search"},
                "broad": {"type": "boolean", "description": "Include broad results"},
                "limit": {"type": "integer", "description": "Maximum number of results"},
            },
            "required": ["keyword"],
        },
    }
    args = VidiqMcpProvider._arguments(tool, TopicDiscoveryRequest(mode="EVERGREEN", limit=6))
    assert args == {
        "keyword": "mixed curiosity explainers YouTube topic opportunities",
        "limit": 6,
    }


def test_provider_uses_advertised_boolean_default_and_rejects_unmapped_required_field():
    tool = {
        "name": "keyword_research",
        "inputSchema": {
            "type": "object",
            "properties": {
                "broad": {"type": "boolean", "default": False},
                "country": {"type": "string"},
            },
            "required": ["country"],
        },
    }
    with pytest.raises(ProviderUnavailableError, match="requires the 'country' argument"):
        VidiqMcpProvider._arguments(tool, TopicDiscoveryRequest())
    tool["inputSchema"]["required"] = []
    assert VidiqMcpProvider._arguments(tool, TopicDiscoveryRequest()) == {"broad": False}


@pytest.mark.parametrize("field", ["language", "locale"])
def test_provider_normalizes_locale_to_language_code_without_enum(field):
    tool = {
        "name": "keyword_research",
        "inputSchema": {
            "type": "object",
            "properties": {field: {"type": "string"}},
        },
    }
    args = VidiqMcpProvider._arguments(tool, TopicDiscoveryRequest(locale="English"))
    assert args == {field: "en"}


def test_provider_selects_vidiq_keyword_tool_with_underscored_name():
    tools = [
        {"name": "keyword_research", "description": "Research related keywords"},
        {"name": "video_watch", "description": "Analyze a YouTube video"},
    ]
    assert VidiqMcpProvider._select_tool(tools, "EVERGREEN")["name"] == "keyword_research"


def test_trending_mode_requires_a_trend_discovery_tool():
    tools = [{"name": "keyword_research", "description": "Research related keywords"}]
    assert VidiqMcpProvider._select_tool(tools, "TRENDING") is None


def test_provider_parses_structured_candidate_without_inventing_metrics():
    record = {"keyword": "Why do cats purr?", "search_volume": 3200, "related_keywords": ["cat purring"]}
    item = VidiqMcpProvider._candidate(record, 0)
    assert item.topic == "Why do cats purr?"
    assert item.evidence["search_volume"].value == 3200
    assert "competition" not in item.evidence
    assert item.raw_evidence == record


def test_provider_applies_requested_mode_if_result_does_not_label_candidate():
    item = VidiqMcpProvider._candidate({"keyword": "A durable question"}, 0, "EVERGREEN")
    assert item.opportunity_type == "EVERGREEN"


def test_provider_uses_mcp_initialize_discovery_and_structured_result():
    session = FakeMcpSession()
    provider = VidiqMcpProvider(api_key="test-key", session=session)
    found = provider.discover(TopicDiscoveryRequest())
    assert found[0].topic == "Why do birds migrate?"
    methods = [call["json"]["method"] for call in session.calls]
    assert methods == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    assert all(call["headers"]["Authorization"] == "Bearer test-key" for call in session.calls)
    assert all(
        call["headers"].get("MCP-Protocol-Version") == "2025-03-26"
        for call in session.calls[1:]
    )


def test_provider_rejects_non_candidate_prose():
    assert VidiqMcpProvider._extract_records({"content": [{"type": "text", "text": "Here are some ideas"}]}) == []


def test_provider_extracts_vidiq_camel_case_rising_keyword_payload():
    result = {"structuredContent": {"risingKeywords": [{"keyword": "New curiosity topic", "searchDemandGrowthPct": 40}]}}
    rows = VidiqMcpProvider._extract_records(result)
    assert rows[0]["keyword"] == "New curiosity topic"
    assert VidiqMcpProvider._candidate(rows[0], 0).evidence["growth"].value == 40


def test_provider_extracts_only_explicit_topic_rows_from_text_response():
    result = {
        "content": [{
            "type": "text",
            "text": chr(10).join([
                "Rising keywords this week:",
                "1. Why do cats purr? | growth: 40%",
                "2. Why is the sky blue?",
                "No extra candidates.",
            ]),
        }]
    }
    rows = VidiqMcpProvider._extract_records(result)
    assert [row["keyword"] for row in rows] == ["Why do cats purr?", "Why is the sky blue?"]
    assert rows[0]["provider_text"] == "Why do cats purr? | growth: 40%"


def test_provider_extracts_string_candidates_from_nested_vidiq_payload():
    result = {
        "structuredContent": {
            "data": {"rising_keywords": ["Why do owls turn their heads?", "How deep is the ocean?"]}
        }
    }
    rows = VidiqMcpProvider._extract_records(result)
    assert [row["keyword"] for row in rows] == [
        "Why do owls turn their heads?",
        "How deep is the ocean?",
    ]


def test_provider_extracts_markdown_table_and_keeps_metric_values_as_evidence():
    result = {
        "content": [{
            "type": "text",
            "text": "| Keyword | Search Volume | Volume Change |\n| --- | ---: | ---: |\n| Why do cats purr? | 12,000 | 40% |",
        }]
    }
    rows = VidiqMcpProvider._extract_records(result)
    assert rows == [{
        "keyword": "Why do cats purr?",
        "provider_text": "| Why do cats purr? | 12,000 | 40% |",
        "searchvolume": "12,000",
        "volumechange": "40%",
    }]
    item = VidiqMcpProvider._candidate(rows[0], 0)
    assert item.evidence["search_volume"].value == "12,000"
    assert item.evidence["growth"].value == "40%"


def test_provider_extracts_json_embedded_in_tool_text():
    result = {
        "content": [{
            "type": "text",
            "text": 'Results from vidIQ:\n```json\n{"keywords":[{"keyword":"Why do leaves change color?"}]}\n```',
        }]
    }
    rows = VidiqMcpProvider._extract_records(result)
    assert rows[0]["keyword"] == "Why do leaves change color?"


def test_provider_flattens_nested_outlier_videos():
    rows = VidiqMcpProvider._extract_records({
        "structuredContent": {
            "keyword": "history mysteries",
            "videos": [{"videoId": "abc", "videoTitle": "A mystery", "viewCount": 123}],
        }
    })
    assert rows == [{"videoId": "abc", "videoTitle": "A mystery", "viewCount": 123}]
    item = normalize_outlier(rows[0])
    assert item.title == "A mystery"
    assert item.views == 123


def test_top_outliers_uses_breakout_score_without_promoting_raw_views():
    report = type("Report", (), {"outliers": [
        normalize_outlier({"videoId": "a", "videoTitle": "A", "breakoutScore": 20, "viewCount": 1000}),
        normalize_outlier({"videoId": "b", "videoTitle": "B", "breakoutScore": 80, "viewCount": 10}),
    ]})()
    assert [item.video_id for item in top_outliers(report)] == ["b", "a"]


def test_provider_response_shape_diagnostic_redacts_credential_like_text():
    shape = VidiqMcpProvider._response_shape({
        "content": [{"type": "text", "text": "private topic response\nBearer supersecret-token-value"}],
        "isError": False,
    })
    assert "text_length=53" in shape
    assert "private topic response" in shape
    assert "supersecret-token-value" not in shape
    assert "[REDACTED]" in shape


def test_missing_key_is_clear_and_does_not_make_network_call():
    provider = VidiqMcpProvider(api_key=None)
    with pytest.raises(ProviderUnavailableError, match="VIDIQ_MCP_API_KEY"):
        provider.discover(TopicDiscoveryRequest())


def test_network_errors_are_reported_without_leaking_request_details():
    class BrokenSession:
        def post(self, *args, **kwargs):
            raise requests.ConnectionError("connection failure with private detail")

    provider = VidiqMcpProvider(api_key="test-key", session=BrokenSession())
    with pytest.raises(ProviderUnavailableError, match="Could not connect") as error:
        provider.discover(TopicDiscoveryRequest())
    assert "private detail" not in str(error.value)


class FakeProvider:
    name = "fixture"

    def __init__(self):
        self.calls = 0

    def discover(self, request):
        self.calls += 1
        return [candidate("Test topic", search_volume=55)]


class FakeEditorialEvaluator:
    model_name = "fixture-model"
    prompt_version = "fixture-prompt-v1"

    def __init__(self):
        self.calls = 0

    def assess(self, candidates):
        self.calls += 1
        return [
            CandidateEditorialAssessment(
                candidate_id=item.candidate_id,
                audience_fit=85,
                curiosity=80,
                evergreen=70,
                visual=75,
                researchability=90,
                differentiation=60,
                saturation=65,
                status="PASS",
                rationale=["Fits the curiosity explainer format."],
            )
            for item in candidates
        ]


def test_engine_attaches_competitor_evidence_separately_from_ritzz_signals(tmp_path):
    class ProviderWithCompetitorResearch(FakeProvider):
        def discover(self, request):
            return [
                candidate(
                    "Why do cats purr?",
                    search_volume=1200,
                    growth="25%",
                    competition=42,
                )
            ]

        def discover_competitor_research(self, query, limit=10):
            return build_market_intelligence_report(
                query,
                [{
                    "videoId": "cat-video",
                    "videoTitle": "Why Cats Purr",
                    "channelId": "cat-channel",
                    "channelTitle": "Cat Science",
                    "viewCount": 800,
                    "baselineViews": 100,
                }, {
                    "videoId": "cat-video-2",
                    "videoTitle": "Why Do Cats Purr?",
                    "channelId": "cat-channel-2",
                    "channelTitle": "Animal Answers",
                    "viewCount": 700,
                    "baselineViews": 200,
                }],
            )

    report = TopicIntelligenceEngine(
        provider=ProviderWithCompetitorResearch(),
        cache_dir=tmp_path,
        editorial_evaluator=FakeEditorialEvaluator(),
    ).discover()
    item = report.candidates[0]

    assert item.competitor_topic_performance_available is True
    assert len(item.competitor_evidence) == 2
    assert item.competitor_evidence[0].channel["name"] == "Cat Science"
    assert item.competitor_evidence[0].observed_performance["views"] == 800
    assert item.competitor_topic_patterns[0].video_count == 2
    assert item.competitor_topic_patterns[0].channel_count == 2
    assert item.current_vidiq_demand_signals["search_volume"].value == 1200
    assert item.competition_saturation_signal is not None
    assert item.competition_saturation_signal.value == 42
    assert item.competition_saturation_assessment is not None
    assert "higher raw competition values reduce attractiveness" in item.competition_saturation_assessment
    assert "across 2 competitor channels" in item.competition_saturation_assessment
    assert item.ritzz_differentiation_angle == item.angle
    assert "search_volume" in item.evidence


def test_engine_caches_discovery_and_force_refreshes(tmp_path):
    provider = FakeProvider()
    evaluator = FakeEditorialEvaluator()
    engine = TopicIntelligenceEngine(provider=provider, cache_dir=tmp_path, editorial_evaluator=evaluator)
    first = engine.discover(TopicDiscoveryRequest())
    cached = engine.discover(TopicDiscoveryRequest())
    refreshed = engine.discover(TopicDiscoveryRequest(force_refresh=True))
    assert provider.calls == 2
    assert evaluator.calls == 2
    assert first.report_id == cached.report_id == refreshed.report_id
    assert cached.cached is True
    assert first.editorial_model == "fixture-model"
    assert first.editorial_prompt_version == "fixture-prompt-v1"
    assert json.loads(next(tmp_path.glob("*.json")).read_text())


def test_editorial_assessment_failure_preserves_provider_candidate(tmp_path):
    class BrokenAssessment:
        def assess(self, candidates):
            raise RuntimeError("temporary model failure")

    report = TopicIntelligenceEngine(
        provider=FakeProvider(),
        cache_dir=tmp_path,
        editorial_evaluator=BrokenAssessment(),
    ).discover()
    assert report.candidates[0].topic == "Test topic"
    assert report.candidates[0].editorial_scores == {}
    assert any("editorial scoring was unavailable" in warning for warning in report.warnings)


def test_editorial_assessments_are_applied_separately_from_provider_evidence():
    item = candidate("Why do cats purr?", search_volume=1200)
    assessment = CandidateEditorialAssessment(
        candidate_id=item.candidate_id,
        audience_fit=90,
        curiosity=88,
        evergreen=80,
        visual=70,
        researchability=85,
        differentiation=75,
        saturation=60,
        status="PASS",
        rationale=["Can be explained visually."],
    )
    apply_editorial_assessments([item], [assessment])
    assert item.editorial_scores["audience_fit"] == 90
    assert item.editorial_status == "PASS"
    assert "search_volume" in item.evidence


def test_openai_editorial_evaluator_requires_all_candidate_ids():
    class FakeResponses:
        def parse(self, **kwargs):
            return type("Response", (), {"output_parsed": CandidateEditorialAssessments(assessments=[])})()

    client = type("FakeClient", (), {"responses": FakeResponses()})()
    evaluator = EditorialEvaluator(client=client)
    with pytest.raises(ValueError, match="candidate mismatch"):
        evaluator.assess([candidate("Topic")])


def test_editorial_fail_flag_ranks_after_pass_without_deleting_candidate():
    passing = candidate("Pass topic", search_volume=20)
    passing.editorial_status = "PASS"
    flagged = candidate("Flagged topic", search_volume=100)
    flagged.editorial_status = "FAIL"
    ranked = rank_candidates([flagged, passing])
    assert [item.topic for item in ranked] == ["Pass topic", "Flagged topic"]


def test_validation_gate_deduplicates_and_keeps_review_candidates_visible():
    primary = candidate("The Art of War", search_volume=100, competition=20)
    primary.editorial_status = "PASS"
    primary.editorial_scores = {name: 80 for name in (
        "audience_fit", "curiosity", "evergreen", "visual", "researchability",
        "differentiation", "saturation",
    )}
    duplicate = candidate("Art of War", search_volume=90, competition=30)
    duplicate.editorial_status = "PASS"
    duplicate.editorial_scores = primary.editorial_scores.copy()
    ranked = rank_candidates([primary, duplicate])

    shortlist = validate_candidates(ranked)

    assert shortlist == [primary.candidate_id]
    assert primary.validation_status == "RECOMMENDED"
    assert duplicate.validation_status == "REVIEW"
    assert any("duplicate" in reason.casefold() for reason in duplicate.validation_reasons)


def test_validation_gate_holds_low_evidence_topics_for_review():
    item = candidate("A promising topic", search_volume=100)
    item.editorial_status = "PASS"
    item.opportunity_score = 80
    item.score_completeness = 0.4

    assert validate_candidates([item]) == []
    assert item.validation_status == "REVIEW"
    assert any("completeness" in reason.casefold() for reason in item.validation_reasons)
