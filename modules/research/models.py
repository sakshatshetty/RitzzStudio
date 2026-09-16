from typing import Literal

from pydantic import BaseModel, Field


ImportanceLevel = Literal["high", "medium", "low"]
ConfidenceLevel = Literal["high", "medium", "low"]
SourceTier = Literal["1", "2", "3", "4"]

SourceType = Literal[
    "government",
    "university",
    "academic",
    "museum",
    "journalism",
    "reference",
    "other",
]


class Source(BaseModel):
    """A source supporting one or more research claims."""

    id: str
    title: str
    url: str
    publisher: str
    relevance: str

    tier: SourceTier = Field(
        description=(
            "Source quality tier. "
            "1 = highest authority, 4 = lowest."
        )
    )

    source_type: SourceType = Field(
        description="Type of source."
    )


class KeyFact(BaseModel):
    """A factual claim discovered during research."""

    fact: str
    importance: ImportanceLevel = Field(
        description="Importance of this fact for the video."
    )
    confidence: ConfidenceLevel = Field(
        description="Confidence that this fact is accurately supported."
    )
    sources: list[str] = Field(default_factory=list)


class HistoricalContext(BaseModel):
    """Historical or contextual information relevant to the topic."""

    fact: str
    period: str
    sources: list[str] = Field(default_factory=list)


class Myth(BaseModel):
    """A common misconception and the evidence-based reality."""

    claim: str
    reality: str
    sources: list[str] = Field(default_factory=list)


class SurprisingFact(BaseModel):
    """A potentially interesting or surprising factual detail."""

    fact: str
    sources: list[str] = Field(default_factory=list)


class Research(BaseModel):
    """Complete structured research for a Ritzz video."""

    topic: str
    category: str
    core_question: str
    short_answer: str

    key_facts: list[KeyFact] = Field(default_factory=list)

    historical_context: list[HistoricalContext] = Field(
        default_factory=list
    )

    common_myths: list[Myth] = Field(default_factory=list)

    surprising_facts: list[SurprisingFact] = Field(
        default_factory=list
    )

    possible_story_angles: list[str] = Field(
        default_factory=list
    )

    sources: list[Source] = Field(default_factory=list)