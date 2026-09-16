from typing import Literal

from pydantic import BaseModel, Field


SectionType = Literal[
    "hook",
    "setup",
    "question",
    "explanation",
    "myth",
    "context",
    "payoff",
    "conclusion",
]


class OutlineSection(BaseModel):
    """A single section of a Ritzz video outline."""

    section_id: str
    section_type: SectionType
    title: str
    purpose: str
    key_points: list[str] = Field(default_factory=list)

    estimated_seconds: int = Field(
        ge=10,
        le=180,
    )

    research_sources: list[str] = Field(
        default_factory=list
    )


class Outline(BaseModel):
    """Complete outline for a Ritzz video."""

    topic: str
    target_duration_seconds: int = 480

    hook: str

    sections: list[OutlineSection] = Field(
        default_factory=list
    )

    total_estimated_seconds: int

    closing_message: str