import json

import pytest
from pydantic import ValidationError

from modules.topic_intelligence.inventory import (
    ContentInventoryEntry,
    ContentInventoryManager,
    normalize_topic,
)
from modules.topic_intelligence.models import (
    RITZZ_CHANNEL_PROFILE,
    EvidenceMetric,
    OpportunityCandidate,
    OpportunityReport,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.pipeline_topic_discovery import (
    PIPELINE_TOPIC_SOURCE,
    TOPIC_OPPORTUNITY_COUNT,
    VIDIQ_DISCOVERY_QUERY,
    GeneratedTopicBatch,
    GeneratedTopicIdea,
    GPTKeywordTopicDiscovery,
    GPTTopicIdeaGenerator,
    TopicDiscoveryFailure,
    format_metric_value,
)
from modules.topic_intelligence.providers.base import ProviderUnavailableError
from modules.topic_intelligence.providers.vidiq_mcp import VidiqMcpProvider

_TITLES = [
    "Why Did Ancient Builders Build Roads in Layers?",
    "How Did Roman Engineers Move Water Uphill?",
    "Why Did Medieval Towns Build Walls Around Their Markets?",
    "What Made the Antikythera Mechanism So Hard to Recreate?",
    "Why Did Ancient Sailors Follow the Stars at Night?",
    "How Did Inca Builders Fit Stones Without Mortar?",
    "Why Did Early Maps Draw Sea Monsters at Their Edges?",
    "How Did London Streets Change After the Great Fire?",
    "Why Did the Panama Canal Need a Chain of Locks?",
    "How Did the Hubble Telescope Change Our View of Space?",
]

_OPPORTUNITIES = [
    "ancient road layers",
    "Roman aqueduct engineering",
    "medieval market walls",
    "Antikythera mechanism",
    "ancient navigation stars",
    "Inca stonework",
    "sea monsters on maps",
    "Great Fire of London streets",
    "Panama Canal locks",
    "Hubble discoveries",
]


def _metric(value: float | None, metric: str) -> EvidenceMetric:
    units = {
        "keyword_score": "0-100",
        "volume_score": "0-100",
        "search_volume": "monthly searches",
        "competition": "0-100",
    }
    return EvidenceMetric(
        value=value,
        unit=units[metric] if value is not None else None,
        available=value is not None,
        source="vidIQ MCP",
    )


def _opportunity(index: int, *, metrics: bool = True) -> OpportunityCandidate:
    evidence = (
        {
            "keyword_score": _metric(90 - index, "keyword_score"),
            "volume_score": _metric(80 - index, "volume_score"),
            "search_volume": _metric(2000 - index * 10, "search_volume"),
            "competition": _metric(35 + index, "competition"),
        }
        if metrics
        else {}
    )
    return OpportunityCandidate(
        candidate_id=f"opp-{index + 1:02d}",
        topic=_OPPORTUNITIES[index % len(_OPPORTUNITIES)],
        primary_keyword=_OPPORTUNITIES[index % len(_OPPORTUNITIES)],
        related_keywords=[f"related {index}"],
        related_questions=[f"How did opportunity {index} work?"],
        evidence=evidence,
        provider="vidIQ MCP",
        raw_evidence={
            "source_row": index,
            "keyword": _OPPORTUNITIES[index % len(_OPPORTUNITIES)],
        },
    )


def _idea(
    index: int,
    *,
    title: str | None = None,
    source_opportunity_id: str | None = None,
) -> GeneratedTopicIdea:
    return GeneratedTopicIdea(
        title=title or _TITLES[index % len(_TITLES)],
        source_opportunity_id=source_opportunity_id or f"opp-{index + 1:02d}",
        angle="Explain the surprising engineering choice and the problem it solved.",
        curiosity_hook="The design seems impossible until its practical purpose becomes clear.",
        static_visual_explanation="Show a labeled cutaway diagram, a simple map, and the key object.",
        long_form_depth="Cover the original problem, the design, how it worked, and its lasting effects.",
        originality_note="Focus on the overlooked engineering problem rather than a generic history summary.",
    )


class FakeVidiqProvider:
    name = "fake-vidiq"

    def __init__(
        self,
        opportunities: list[OpportunityCandidate] | None = None,
        *,
        failure: Exception | None = None,
    ):
        self.opportunities = (
            opportunities
            if opportunities is not None
            else [_opportunity(index) for index in range(TOPIC_OPPORTUNITY_COUNT)]
        )
        self.failure = failure
        self.calls: list[TopicDiscoveryRequest] = []

    def discover(self, request: TopicDiscoveryRequest) -> list[OpportunityCandidate]:
        self.calls.append(request)
        if self.failure is not None:
            raise self.failure
        return self.opportunities


class FakeGenerator:
    def __init__(
        self,
        ideas: list[GeneratedTopicIdea] | None = None,
        *,
        failure: Exception | None = None,
    ):
        self.ideas = ideas or [_idea(index) for index in range(10)]
        self.failure = failure
        self.calls: list[list[OpportunityCandidate]] = []

    def generate(
        self,
        opportunities: list[OpportunityCandidate],
    ) -> list[GeneratedTopicIdea]:
        self.calls.append(opportunities)
        if self.failure is not None:
            raise self.failure
        return self.ideas


def _discover(
    tmp_path,
    *,
    ideas: list[GeneratedTopicIdea] | None = None,
    opportunities: list[OpportunityCandidate] | None = None,
    provider_failure: Exception | None = None,
    generator_failure: Exception | None = None,
) -> tuple[
    OpportunityReport,
    FakeVidiqProvider,
    FakeGenerator,
]:
    provider = FakeVidiqProvider(opportunities, failure=provider_failure)
    generator = FakeGenerator(ideas, failure=generator_failure)
    discovery = GPTKeywordTopicDiscovery(
        provider,
        ContentInventoryManager(tmp_path / "inventory.json"),
        generator=generator,
    )
    report = discovery.discover(TopicDiscoveryRequest(pipeline_topic_gate=True))
    return report, provider, generator


def test_vidiq_receives_ritzz_profile_once_and_returns_opportunity_pool(tmp_path):
    report, provider, generator = _discover(tmp_path)

    assert len(provider.calls) == 1
    assert provider.calls[0].niche == VIDIQ_DISCOVERY_QUERY
    assert provider.calls[0].mode == "EVERGREEN"
    assert provider.calls[0].limit == TOPIC_OPPORTUNITY_COUNT
    assert report.discovery_diagnostics["vidiq_discovery_operation_count"] == 1
    assert report.discovery_diagnostics["vidiq_opportunities_returned"] == 20
    assert len(generator.calls) == 1


def test_gpt_receives_vidiq_pool_and_generates_concepts_in_one_request():
    opportunities = [_opportunity(index) for index in range(12)]
    ideas = [_idea(index) for index in range(9)]

    class Responses:
        def __init__(self):
            self.calls: list[dict] = []

        def parse(self, **kwargs):
            self.calls.append(kwargs)
            return type(
                "Response",
                (),
                {"output_parsed": GeneratedTopicBatch(ideas=ideas)},
            )()

    class Client:
        def __init__(self):
            self.responses = Responses()

    client = Client()
    generated = GPTTopicIdeaGenerator(client=client).generate(opportunities)

    assert generated == ideas
    assert len(client.responses.calls) == 1
    user_payload = json.loads(client.responses.calls[0]["input"][1]["content"])
    assert len(user_payload["vidiq_opportunities"]) == 12
    assert user_payload["channel_profile"] == RITZZ_CHANNEL_PROFILE
    assert user_payload["vidiq_opportunities"][0]["topic_or_keyword"] == opportunities[0].topic
    assert user_payload["vidiq_opportunities"][0]["keyword_score"]["value"] == 90
    assert user_payload["vidiq_opportunities"][0]["volume_score"]["value"] == 80
    assert "Do not simply repeat a keyword" in user_payload["instructions"]
    system_prompt = client.responses.calls[0]["input"][0]["content"].casefold()
    assert "ancient humans" in system_prompt
    assert "ancient civilizations" in system_prompt
    assert "specific ancient-human situation" in system_prompt
    assert "survival, daily life, behavior, food, sleep, travel, shelter" in system_prompt
    assert "practical engineering/technology" in system_prompt
    assert "use competitor opportunities as curiosity-pattern signals" in system_prompt
    assert "generic ancient-history labels" in system_prompt
    assert "current disasters" in system_prompt
    assert user_payload["channel_profile"] == RITZZ_CHANNEL_PROFILE


def test_pipeline_generates_one_idea_batch_filters_and_preserves_market_evidence(tmp_path):
    report, provider, generator = _discover(tmp_path)

    assert len(provider.calls) == 1
    assert len(generator.calls) == 1
    assert len(generator.calls[0]) == 20
    assert report.discovery_diagnostics["gpt_calls_made"] == 1
    assert report.discovery_diagnostics["gpt_ideas_generated"] == 10
    assert report.discovery_diagnostics["vidiq_usage_mode"] == "DISCOVERY_ONLY"
    assert report.discovery_diagnostics["discovery_mode"] == "VIDIQ_TO_GPT"
    assert len(report.candidates) == 5
    candidate = report.candidates[0]
    assert candidate.provider == PIPELINE_TOPIC_SOURCE
    assert candidate.discovery_sources == ["vidiq_discovery", "gpt_ideation"]
    assert candidate.raw_evidence["vidiq_opportunity"]["topic"] == _OPPORTUNITIES[0]
    assert candidate.evidence["keyword_score"].value == 90
    assert candidate.evidence["search_volume"].value == 2000
    assert candidate.evidence["competition"].value == 35
    assert candidate.raw_evidence["vidiq_opportunity"]["raw_evidence"]["source_row"] == 0
    assert report.discovery_diagnostics["status"] == "SUCCESS"
    assert not hasattr(report, "selected_candidate_id")


def test_broad_non_ritzz_duplicate_and_inventory_ideas_are_rejected(tmp_path):
    ideas = [
        _idea(0, title="The Strange World of Space"),
        _idea(1, title="Why Is Celebrity Gossip Everywhere?"),
        _idea(2, title="The History of England"),
        _idea(3, title="Why Did Roman Engineers Move Water Uphill?"),
        _idea(4, title="Why Did Ancient Sailors Follow the Stars at Night?"),
        _idea(5, title="How Did Inca Builders Fit Stones Without Mortar?"),
        _idea(6, title="Why Did Early Maps Draw Sea Monsters at Their Edges?"),
        _idea(7, title="How Did London Streets Change After the Great Fire?"),
        _idea(8, title="Why Did the Panama Canal Need a Chain of Locks?"),
        _idea(9, title="How Did the Hubble Telescope Change Our View of Space?"),
    ]
    inventory = ContentInventoryManager(tmp_path / "inventory.json")
    inventory.add(ContentInventoryEntry(
        topic=ideas[4].title,
        normalized_topic=normalize_topic(ideas[4].title),
        project_id="existing",
    ))
    report, _, _ = _discover(tmp_path, ideas=ideas)

    reasons = "\n".join(
        rejected["reason"]
        for rejected in report.discovery_diagnostics["ideas_rejected"]
    )
    assert "too broad" in reasons
    assert "celebrity or gossip" in reasons
    assert "Overlaps existing RITZZ inventory" in reasons
    assert len(report.candidates) == 5
    assert all(candidate.inventory_status == "ELIGIBLE" for candidate in report.candidates)


def test_unmatched_opportunity_and_near_duplicate_ideas_are_rejected(tmp_path):
    ideas = [_idea(index) for index in range(8)]
    ideas[0] = _idea(0, source_opportunity_id="not-from-vidiq")
    ideas[1] = _idea(1, title="Why Did Roman Engineers Move Water Uphill?")
    ideas[2] = _idea(2, title="Why Did Roman Engineer Move Water Uphill?")

    report, _, _ = _discover(tmp_path, ideas=ideas)

    reasons = "\n".join(
        rejected["reason"]
        for rejected in report.discovery_diagnostics["ideas_rejected"]
    )
    assert "not returned by vidIQ" in reasons
    assert "Near-duplicate" in reasons


def test_two_qualified_ideas_pass_with_one_vidiq_and_one_gpt_call(tmp_path):
    ideas = [
        _idea(0),
        _idea(1),
        *[
            _idea(index, title="The Strange World of Space")
            for index in range(2, 8)
        ],
    ]

    report, provider, generator = _discover(tmp_path, ideas=ideas)

    assert len(report.candidates) == 2
    assert report.discovery_diagnostics["status"] == "SUCCESS"
    assert len(provider.calls) == 1
    assert len(generator.calls) == 1


def test_missing_vidiq_metrics_remain_unavailable_without_fabricated_values(tmp_path):
    opportunities = [_opportunity(index, metrics=False) for index in range(10)]
    report, _, _ = _discover(tmp_path, opportunities=opportunities)

    assert len(report.candidates) == 5
    assert report.candidates[0].vidiq_status == "UNAVAILABLE"
    assert report.candidates[0].evidence == {}
    assert report.candidates[0].current_vidiq_demand_available is False


def test_vidiq_failure_is_classified_without_openai_fallback(tmp_path):
    failure = ProviderUnavailableError(
        "vidIQ API unavailable",
        error_type="INSUFFICIENT_CREDITS",
        tool="keyword_research",
    )
    provider = FakeVidiqProvider(failure=failure)
    generator = FakeGenerator()
    discovery = GPTKeywordTopicDiscovery(
        provider,
        ContentInventoryManager(tmp_path / "inventory.json"),
        generator=generator,
    )

    with pytest.raises(TopicDiscoveryFailure) as error:
        discovery.discover(TopicDiscoveryRequest(pipeline_topic_gate=True))

    assert error.value.diagnostics["status"] == "VIDIQ_PROVIDER_ERROR"
    assert error.value.diagnostics["provider_error_type"] == "INSUFFICIENT_CREDITS"
    assert error.value.diagnostics["vidiq_discovery_operation_count"] == 1
    assert len(provider.calls) == 1
    assert generator.calls == []


def test_empty_vidiq_response_is_provider_error_not_no_topics(tmp_path):
    provider = FakeVidiqProvider(opportunities=[])
    generator = FakeGenerator()
    discovery = GPTKeywordTopicDiscovery(
        provider,
        ContentInventoryManager(tmp_path / "inventory.json"),
        generator=generator,
    )

    with pytest.raises(TopicDiscoveryFailure) as error:
        discovery.discover(TopicDiscoveryRequest(pipeline_topic_gate=True))

    assert error.value.diagnostics["status"] == "VIDIQ_PROVIDER_ERROR"
    assert error.value.diagnostics["provider_error_type"] == "EMPTY_DISCOVERY_RESPONSE"
    assert generator.calls == []


def test_small_vidiq_pool_stops_before_gpt_to_avoid_ungrounded_ideas(tmp_path):
    provider = FakeVidiqProvider(opportunities=[_opportunity(0), _opportunity(1)])
    generator = FakeGenerator()
    discovery = GPTKeywordTopicDiscovery(
        provider,
        ContentInventoryManager(tmp_path / "inventory.json"),
        generator=generator,
    )

    with pytest.raises(TopicDiscoveryFailure) as error:
        discovery.discover(TopicDiscoveryRequest(pipeline_topic_gate=True))

    assert error.value.diagnostics["status"] == "INSUFFICIENT_VIDIQ_OPPORTUNITIES"
    assert error.value.diagnostics["vidiq_opportunities_returned"] == 2
    assert len(provider.calls) == 1
    assert generator.calls == []


def test_gpt_failure_is_classified_and_does_not_use_partial_ideas(tmp_path):
    provider = FakeVidiqProvider()
    generator = FakeGenerator(failure=RuntimeError("GPT unavailable"))
    discovery = GPTKeywordTopicDiscovery(
        provider,
        ContentInventoryManager(tmp_path / "inventory.json"),
        generator=generator,
    )

    with pytest.raises(TopicDiscoveryFailure) as error:
        discovery.discover(TopicDiscoveryRequest(pipeline_topic_gate=True))

    assert error.value.diagnostics["status"] == "OPENAI_PROVIDER_ERROR"
    assert len(provider.calls) == 1
    assert len(generator.calls) == 1


def test_generator_requires_eight_to_ten_ideas():
    with pytest.raises(ValidationError):
        GeneratedTopicBatch(ideas=[_idea(index) for index in range(7)])
    with pytest.raises(ValidationError):
        GeneratedTopicBatch(ideas=[_idea(index) for index in range(11)])


def test_metric_formatting_keeps_large_search_counts_readable():
    assert format_metric_value(6_302_913.0) == "6,302,913"
    assert format_metric_value(61.7) == "61.7"


@pytest.mark.parametrize("idea_count,expected_count", [(8, 5), (9, 5), (10, 5)])
def test_shortlist_is_two_to_five_and_never_selects_automatically(
    tmp_path,
    idea_count,
    expected_count,
):
    ideas = [_idea(index) for index in range(idea_count)]
    report, _, _ = _discover(tmp_path, ideas=ideas)

    assert len(report.candidates) == expected_count
    assert 2 <= len(report.candidates) <= 5
    assert report.shortlist_candidate_ids
    assert not (tmp_path / "topic_selection.json").exists()
    assert report.discovery_diagnostics["status"] == "SUCCESS"
    assert report.discovery_diagnostics["ideas_rejected_count"] == idea_count - 5
    assert all(
        "shortlist limit" in idea["reason"]
        for idea in report.discovery_diagnostics["ideas_rejected"]
    )


@pytest.mark.parametrize("valid_count", [3, 4, 5])
def test_shortlist_allows_three_four_or_five_qualified_ideas(tmp_path, valid_count):
    ideas = [
        _idea(index) if index < valid_count else _idea(index, title="History of England")
        for index in range(8)
    ]
    report, _, _ = _discover(tmp_path, ideas=ideas)

    assert len(report.candidates) == valid_count
    assert report.discovery_diagnostics["status"] == "SUCCESS"


def test_fewer_than_two_qualified_ideas_does_not_retry_or_manufacture_candidates(
    tmp_path,
):
    ideas = [
        _idea(0, title="History of England"),
        _idea(1, title="The Strange World of Space"),
        _idea(2, title="Why Is Celebrity Gossip Everywhere?"),
        _idea(3, title="The History of France"),
        _idea(4, title="Why Is Sports News Everywhere?"),
        _idea(5, title="The Art of War"),
        _idea(6, title="How Can You Get Better Weight Loss Tips?"),
        _idea(7, title="The History of Rome"),
    ]
    report, provider, generator = _discover(tmp_path, ideas=ideas)

    assert len(report.candidates) == 0
    assert report.discovery_diagnostics["status"] == "INSUFFICIENT_QUALIFIED_TOPICS"
    assert len(provider.calls) == 1
    assert len(generator.calls) == 1


def test_vidiq_discovery_adapter_uses_one_keyword_research_tool_call():
    class MockedVidiqProvider(VidiqMcpProvider):
        def __init__(self):
            super().__init__(api_key="test")
            self.calls: list[tuple[str, dict]] = []

        def _rpc(self, method, params):
            if method == "tools/list":
                return {
                    "tools": [{
                        "name": "keyword_research",
                        "description": "Research related keywords",
                        "inputSchema": {
                            "properties": {
                                "query": {"type": "string", "maxLength": 150},
                                "limit": {"type": "integer"},
                            },
                            "required": ["query"],
                        },
                    }],
                }
            self.calls.append((params["name"], params["arguments"]))
            return {
                "structuredContent": {
                    "keywords": [
                        {"keyword": "ancient road construction", "score": 88},
                        {"keyword": "Roman water systems", "score": 83},
                    ],
                },
            }

    provider = MockedVidiqProvider()
    opportunities = provider.discover(TopicDiscoveryRequest(
        niche=VIDIQ_DISCOVERY_QUERY,
        mode="EVERGREEN",
        limit=TOPIC_OPPORTUNITY_COUNT,
    ))

    assert len(provider.calls) == 1
    name, arguments = provider.calls[0]
    assert name == "keyword_research"
    assert arguments["query"] == f"{VIDIQ_DISCOVERY_QUERY} YouTube topic opportunities"
    assert len(arguments["query"]) <= 150
    assert arguments["limit"] == TOPIC_OPPORTUNITY_COUNT
    assert len(opportunities) == 2
    assert opportunities[0].evidence["keyword_score"].value == 88
