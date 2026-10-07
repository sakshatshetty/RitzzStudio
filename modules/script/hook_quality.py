from typing import Literal

from pydantic import BaseModel, Field


class HookCandidateScores(BaseModel):
    text: str = Field(min_length=1)
    modern_connection_applicable: bool = False
    modern_situation: str = ""
    modern_solution: str = ""
    shared_problem: str = ""
    ancient_problem: str = ""
    curiosity_question: str = ""
    open_loop_description: str = ""
    stakes_description: str = ""
    visual_opportunity: str = ""
    first_investigation: str = ""
    curiosity_mechanism: str = ""
    curiosity: int = Field(ge=0, le=5)
    tension: int = Field(ge=0, le=5)
    specificity: int = Field(ge=0, le=5)
    stakes: int = Field(ge=0, le=5)
    novelty: int = Field(ge=0, le=5)
    clarity: int = Field(ge=0, le=5)
    open_loop: int = Field(ge=0, le=5)
    payoff_promise: int = Field(ge=0, le=5)
    viewer_relevance: int = Field(default=0, ge=0, le=5)
    factual_support: int = Field(ge=0, le=5)
    source_ids: list[str] = Field(default_factory=list)
    modern_relevance: int | None = Field(default=None, ge=0, le=5)
    problem_clarity: int | None = Field(default=None, ge=0, le=5)
    ancient_connection: int | None = Field(default=None, ge=0, le=5)
    surprise: int | None = Field(default=None, ge=0, le=5)
    conversational_quality: int | None = Field(default=None, ge=0, le=5)
    visual_potential: int | None = Field(default=None, ge=0, le=5)
    story_continuity: int | None = Field(default=None, ge=0, le=5)

    @property
    def quality_score(self) -> float:
        dimensions = (
            self.curiosity,
            self.tension,
            self.specificity,
            self.stakes,
            self.novelty,
            self.clarity,
            self.open_loop,
            self.payoff_promise,
            self.viewer_relevance,
            self.factual_support,
        )
        return sum(dimensions) / len(dimensions)


class HookQualityReview(BaseModel):
    current: HookCandidateScores
    alternatives: list[HookCandidateScores] = Field(min_length=3, max_length=5)
    improvement_notes: list[str] = Field(default_factory=list)
    current_issue_codes: list[
        Literal[
            "HOOK_TOO_GENERIC",
            "NO_MODERN_CONNECTION",
            "NO_ANCIENT_CONNECTION",
            "NO_OPEN_LOOP",
            "ANSWER_REVEALED_TOO_EARLY",
            "TOO_LONG",
            "UNSUPPORTED_CLAIM",
            "WEAK_CURIOSITY",
            "OTHER",
        ]
    ] = Field(default_factory=list)
