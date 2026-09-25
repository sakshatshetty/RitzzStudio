import json

from modules.research.engine import ResearchEngine
from modules.research.models import (
    KeyFact,
    Research,
    Source,
)
from modules.project.config import ProductionConfig


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