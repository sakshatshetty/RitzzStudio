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
from modules.topic_intelligence.inventory import ContentInventoryEntry, ContentInventoryManager, normalize_topic
from modules.topic_intelligence.models import (
    EvidenceMetric,
    OpportunityCandidate,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.providers.base import ProviderUnavailableError
from modules.topic_intelligence.providers.vidiq_mcp import VidiqMcpProvider
from modules.topic_intelligence.market_intelligence import normalize_outlier, top_outliers
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
    items = [candidate("United Nations"), candidate("Celebrity gossip"), candidate("Why do birds migrate?")]
    from modules.topic_intelligence.validation import apply_niche_filter

    apply_niche_filter(items)

    assert items[0].filter_reasons
    assert items[1].filter_reasons
    assert items[2].filter_reasons == []


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


def test_top_outliers_prefers_breakout_score_then_views():
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
