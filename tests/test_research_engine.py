import json

from modules.project.config import ProductionConfig
from modules.research.engine import ResearchEngine
from modules.research.models import (
    HistoricalContext,
    KeyFact,
    Myth,
    Research,
    Source,
    SurprisingFact,
)
from modules.research.validation import validate_research


def test_normalize_source_ids():
    engine = ResearchEngine.__new__(ResearchEngine)

    research = Research(
        topic="Test Topic",
        category="Test",
        core_question="What is the test?",
        short_answer="This is a test.",
key_facts=[
    KeyFact(
        fact="Test fact",
        importance="high",
        confidence="high",
        sources=[
            "https://example.com/source-one"
        ],
    )
],
        historical_context=[],
        common_myths=[],
        surprising_facts=[],
        possible_story_angles=[],
sources=[
    Source(
        id="https://example.com/source-one",
        title="Source One",
        url="https://example.com/source-one",
        publisher="Example",
        relevance="Test source",
        tier="1",
        source_type="museum",
    )
],
    )

    result = engine._normalize_source_ids(research)

    assert result.sources[0].id == "source_001"

    assert result.key_facts[0].sources == [
        "source_001"
    ]


def test_normalize_source_ids_maps_tracked_urls_across_all_claim_types():
    research = Research(
        topic="Test Topic",
        category="History",
        core_question="What is the test?",
        short_answer="A test.",
        key_facts=[
            KeyFact(
                fact="An important sourced claim.",
                importance="high",
                confidence="high",
                sources=["https://example.com/article?utm_source=openai"],
            )
        ],
        historical_context=[
            HistoricalContext(
                fact="Historical context.",
                period="Ancient",
                sources=["https://example.com/article/"],
            )
        ],
        common_myths=[
            Myth(
                claim="A myth.",
                reality="The evidence-based reality.",
                sources=["source-original"],
            )
        ],
        surprising_facts=[
            SurprisingFact(
                fact="A surprising fact.",
                sources=["https://example.com/article?gclid=tracking"],
            )
        ],
        sources=[
            Source(
                id="source-original",
                title="Source",
                url="https://example.com/article",
                publisher="Example",
                relevance="Supports all claims.",
                tier="1",
                source_type="academic",
            )
        ],
    )

    result = ResearchEngine._normalize_source_ids(research)

    assert result.key_facts[0].sources == ["source_001"]
    assert result.historical_context[0].sources == ["source_001"]
    assert result.common_myths[0].sources == ["source_001"]
    assert result.surprising_facts[0].sources == ["source_001"]
    assert validate_research(result).status == "PASS"


def test_normalize_source_ids_leaves_unmatched_urls_for_validation():
    research = Research(
        topic="Test Topic",
        category="History",
        core_question="What is the test?",
        short_answer="A test.",
        key_facts=[
            KeyFact(
                fact="An important sourced claim.",
                importance="high",
                confidence="high",
                sources=["https://unknown.example/article"],
            )
        ],
        sources=[
            Source(
                id="source-original",
                title="Source",
                url="https://example.com/article",
                publisher="Example",
                relevance="Supports a different claim.",
                tier="1",
                source_type="academic",
            )
        ],
    )

    result = ResearchEngine._normalize_source_ids(research)

    assert result.key_facts[0].sources == ["https://unknown.example/article"]
    validation = validate_research(result)
    assert validation.status == "FAIL"
    assert "Unknown source reference" in validation.claims[0].issues[0]


def test_save_and_load_research(tmp_path):
    engine = ResearchEngine.__new__(ResearchEngine)

    research = Research(
        topic="Test Topic",
        category="Science",
        core_question="Why does this happen?",
        short_answer="Because science.",
    )

    research_file = tmp_path / "research.json"

    engine._save_research(
        research_file,
        research,
    )

    assert research_file.exists()

    loaded = engine._load_research(
        research_file
    )

    assert isinstance(loaded, Research)
    assert loaded.topic == "Test Topic"
    assert loaded.category == "Science"


def test_saved_file_contains_valid_json(tmp_path):
    engine = ResearchEngine.__new__(ResearchEngine)

    research = Research(
        topic="Test Topic",
        category="Science",
        core_question="Why?",
        short_answer="Because.",
    )

    research_file = tmp_path / "research.json"

    engine._save_research(
        research_file,
        research,
    )

    data = json.loads(
        research_file.read_text(
            encoding="utf-8"
        )
    )

    assert data["topic"] == "Test Topic"
    assert data["category"] == "Science"


def test_research_prompt_uses_production_duration_and_constraints():
    config = ProductionConfig(
        target_duration_seconds=300,
        minimum_duration_seconds=240,
        constraints=["family friendly"],
    )
    prompt = ResearchEngine._system_prompt(config)
    assert "approximately 5-minute" in prompt