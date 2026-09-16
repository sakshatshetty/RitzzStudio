from typing import Literal

from pydantic import BaseModel, Field


ScriptSectionType = Literal[
    "hook",
    "setup",
    "question",
    "explanation",
    "myth",
    "context",
    "payoff",
    "conclusion",
]


class ScriptSection(BaseModel):
    """A single narrated section of a Ritzz video."""

    section_id: str

    section_type: ScriptSectionType

    title: str

    narration: str = Field(
        min_length=1,
    )

    estimated_seconds: int = Field(
        ge=10,
        le=180,
    )

    research_sources: list[str] = Field(
        default_factory=list
    )


class Script(BaseModel):
    """Complete narration script for a Ritzz video."""

    topic: str

    target_duration_seconds: int = 480

    target_word_count: int = Field(
        ge=500,
        le=2000,
    )

    hook: str = Field(
        min_length=1,
    )

    sections: list[ScriptSection] = Field(
        default_factory=list
    )

    total_estimated_seconds: int

    total_word_count: int

    closing_message: str = Field(
        min_length=1,
    )