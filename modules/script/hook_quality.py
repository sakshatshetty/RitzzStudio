from pydantic import BaseModel, Field


class HookCandidateScores(BaseModel):
    text: str = Field(min_length=1)
    curiosity: int = Field(ge=0, le=5)
    tension: int = Field(ge=0, le=5)
    specificity: int = Field(ge=0, le=5)
    stakes: int = Field(ge=0, le=5)
    novelty: int = Field(ge=0, le=5)
    clarity: int = Field(ge=0, le=5)
    open_loop: int = Field(ge=0, le=5)
    payoff_promise: int = Field(ge=0, le=5)
    factual_support: int = Field(ge=0, le=5)
    source_ids: list[str] = Field(default_factory=list)

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
        )
        return sum(dimensions) / len(dimensions)


class HookQualityReview(BaseModel):
    current: HookCandidateScores
    alternatives: list[HookCandidateScores] = Field(default_factory=list)
    improvement_notes: list[str] = Field(default_factory=list)
