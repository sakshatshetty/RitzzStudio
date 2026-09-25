from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator

OpportunityType = Literal["TRENDING", "EVERGREEN", "TREND_TO_EVERGREEN"]
EditorialStatus = Literal["PASS", "REVIEW", "FAIL"]
ValidationStatus = Literal["RECOMMENDED", "REVIEW", "REJECTED"]


class TopicDiscoveryRequest(BaseModel):
    niche: str = "mixed curiosity explainers"
    timeframe: str = "this month"
    locale: str = "English"
    mode: Literal["TRENDING", "EVERGREEN"] = "TRENDING"
    trend_topic: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
    force_refresh: bool = False


class EvidenceMetric(BaseModel):
    value: float | str | None = None
    unit: str | None = None
    observed_at: str | None = None
    available: bool = False
    source: str


class OpportunityCandidate(BaseModel):
    candidate_id: str
    topic: str
    proposed_title: str | None = None
    angle: str | None = None
    why_interesting: str | None = None
    primary_keyword: str | None = None
    related_keywords: list[str] = Field(default_factory=list)
    related_questions: list[str] = Field(default_factory=list)
    opportunity_type: OpportunityType = "TRENDING"
    evidence: dict[str, EvidenceMetric] = Field(default_factory=dict)
    # Editorial scores use a documented 0-100 scale and may be absent.
    editorial_scores: dict[str, float] = Field(default_factory=dict)
    editorial_status: EditorialStatus | None = None
    component_scores: dict[str, float | None] = Field(default_factory=dict)
    opportunity_score: float | None = None
    score_completeness: float = 0
    rationale: list[str] = Field(default_factory=list)
    filter_reasons: list[str] = Field(default_factory=list)
    validation_status: ValidationStatus = "REVIEW"
    validation_reasons: list[str] = Field(default_factory=list)
    provider: str
    discovered_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    raw_evidence: dict = Field(default_factory=dict)


class OpportunityReport(BaseModel):
    report_id: str
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    request: TopicDiscoveryRequest
    provider: str
    cached: bool = False
    warnings: list[str] = Field(default_factory=list)
    candidates: list[OpportunityCandidate] = Field(default_factory=list)
    scoring_version: str = "ritzz-opportunity-v2"
    editorial_model: str | None = None
    editorial_prompt_version: str | None = None
    validation_version: str = "ritzz-topic-validation-v2"
    shortlist_candidate_ids: list[str] = Field(default_factory=list)
    competitor_report: dict | None = None


class TopicSelection(BaseModel):
    report_id: str | None = None
    candidate_id: str | None = None
    topic: str = Field(min_length=1)
    source: Literal["discovery", "manual"]
    target_duration_seconds: int = Field(default=480, ge=1)
    minimum_duration_seconds: int = Field(default=480, ge=1)
    constraints: list[str] = Field(default_factory=list)
    locked_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    selected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    project_id: str | None = None

    @model_validator(mode="after")
    def validate_duration(self):
        if self.minimum_duration_seconds > self.target_duration_seconds:
            raise ValueError("minimum_duration_seconds cannot exceed target_duration_seconds")
        return self
