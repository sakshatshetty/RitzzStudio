from modules.research.models import (
    HistoricalContext,
    KeyFact,
    Myth,
    Research,
    Source,
    SurprisingFact,
)

from modules.research.sources import SourceManager


def test_research_model():
    research = Research(
        topic="Why Do Pirates Wear Eye Patches?",
        category="History",
        core_question=(
            "Why are pirates traditionally depicted wearing eye patches?"
        ),
        short_answer=(
            "The popular explanation is that an eye patch may have helped "
            "sailors adapt between different light conditions, but there is "
            "no strong historical evidence that pirates commonly wore them "
            "for this reason."
        ),
        key_facts=[
            KeyFact(
                fact=(
                    "Historical evidence that pirates commonly wore "
                    "eye patches is limited."
                ),
                importance="high",
                confidence="high",
                sources=["source_1"],
            )
        ],
        historical_context=[
            HistoricalContext(
                fact=(
                    "Eye patches have appeared in various maritime "
                    "and military contexts."
                ),
                period="Historical period",
                sources=["source_1"],
            )
        ],
        common_myths=[
            Myth(
                claim="Pirates universally wore eye patches.",
                reality=(
                    "There is insufficient historical evidence "
                    "to support this."
                ),
                sources=["source_1"],
            )
        ],
        surprising_facts=[
            SurprisingFact(
                fact=(
                    "The familiar pirate eye-patch image may be more "
                    "strongly associated with later popular culture "
                    "than historical evidence."
                ),
                sources=["source_1"],
            )
        ],
        possible_story_angles=[
            "Did pirates really wear eye patches?",
            "Where did the pirate eye-patch image come from?",
            "Could an eye patch actually have helped sailors see in darkness?",
        ],
        sources=[
           Source(
    id="source_1",
    title="Example Historical Source",
    url="https://example.com",
    publisher="Example Publisher",
    relevance="Supports the historical context.",
    tier="1",
    source_type="museum",
)
        ],
    )

    assert research.topic == "Why Do Pirates Wear Eye Patches?"
    assert research.category == "History"
    assert len(research.key_facts) == 1
    assert research.key_facts[0].confidence == "high"
    assert len(research.historical_context) == 1
    assert len(research.common_myths) == 1
    assert len(research.surprising_facts) == 1
    assert len(research.possible_story_angles) == 3
    assert len(research.sources) == 1
    assert research.sources[0].id == "source_1"


def test_source_manager():
    manager = SourceManager()

    source_1 = manager.add_source(
        title="Example Source One",
        url="https://example.com/one",
        publisher="Example Publisher",
        relevance="Historical background",
    )

    source_2 = manager.add_source(
        title="Example Source Two",
        url="https://example.com/two",
        publisher="Another Publisher",
        relevance="Supporting evidence",
    )

    assert source_1.id == "source_1"
    assert source_2.id == "source_2"

    retrieved = manager.get_source("source_1")

    assert retrieved.title == "Example Source One"
    assert retrieved.url == "https://example.com/one"

    sources = manager.get_all_sources()

    assert len(sources) == 2


def test_source_manager_invalid_id():
    manager = SourceManager()

    try:
        manager.get_source("source_999")
        assert False, "Expected KeyError"
    except KeyError:
        pass