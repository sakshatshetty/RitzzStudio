from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from modules.topic_intelligence.market_intelligence import (
    CompetitorEvidence,
    CompetitorTopicPattern,
)

OpportunityType = Literal["TRENDING", "EVERGREEN", "TREND_TO_EVERGREEN"]
EditorialStatus = Literal["PASS", "REVIEW", "FAIL"]
ValidationStatus = Literal["RECOMMENDED", "REVIEW", "REJECTED"]
RitzzFitStatus = Literal["PASS", "REVIEW", "FAIL"]
StoryType = Literal[
    "HISTORY",
    "SCIENCE",
    "MYSTERY",
    "BIOGRAPHY",
    "ARCHAEOLOGY",
    "GEOGRAPHY",
    "HUMAN_BEHAVIOR",
    "TECHNOLOGY",
    "OTHER",
]

RITZZ_CHANNEL_NICHE = (
    "ancient humans and specific human problems, experiences, and everyday curiosity"
)
RITZZ_CHANNEL_PROFILE = (
    "RITZZ is a long-form faceless YouTube channel using hand-drawn stickman/cartoon "
    "visuals. It focuses primarily on ancient humans, with ancient civilizations as "
    "the main secondary setting. Its primary identity is ancient humans + a specific human problem, "
    "experience, activity, or question + a curiosity-driven how/why/what-did-they-do "
    "explanation. The viewer promise is: how did ancient humans actually live and "
    "deal with things we take for granted today, and what did they do when they faced "
    "a specific challenge? Give highest priority to ancient human survival, daily "
    "life, behavior, food, sleep, travel, shelter, dangers, work, entertainment, "
    "health and survival practices, and tools or inventions. Favor specific, "
    "researchable human situations and practical questions such as how people stayed "
    "safe, found food, travelled, worked, or solved everyday problems. Ancient "
    "civilization everyday life, city problems, practical engineering and technology, "
    "customs, inventions, and archaeology that reveals how people lived are secondary "
    "but welcome, especially when framed as a concrete human-curiosity question. "
    "Ancient mysteries, monuments, construction, and wars are lower priority unless "
    "the question explains how people actually lived, survived, or solved a problem. "
    "Human evolution and other historical periods are allowed when strongly aligned "
    "with this same curiosity pattern. Generic ancient history, broad civilization "
    "overviews, broad archaeology, and generic historical events are low priority. "
    "Avoid modern current events and disasters, politics, sports, celebrity or "
    "entertainment news, movie reviews, generic modern science or geography, finance, "
    "unrelated trends, and broad academic categories. Favor stories suitable for "
    "8–10 minutes and visually explainable with simple characters, environments, "
    "maps, tools, shelters, food, animals, weather, diagrams, timelines, and "
    "before/after comparisons."
)


class TopicDiscoveryRequest(BaseModel):
    niche: str = RITZZ_CHANNEL_NICHE
    timeframe: str = "this month"
    locale: str = "English"
    mode: Literal["TRENDING", "EVERGREEN"] = "TRENDING"
    trend_topic: str | None = None
    limit: int = Field(default=10, ge=1, le=50)
    force_refresh: bool = False
    pipeline_topic_gate: bool = False


class EvidenceMetric(BaseModel):
    value: float | str | None = None
    unit: str | None = None
    observed_at: str | None = None
    available: bool = False
    source: str


class RitzzFitResult(BaseModel):
    fit_status: RitzzFitStatus
    fit_score: float | None = None
    story_type: StoryType = "OTHER"
    curiosity_strength: float | None = None
    researchability: float | None = None
    story_depth: float | None = None
    originality: float | None = None
    visual_potential: float | None = None
    format_fit: float | None = None
    evergreen_potential: float | None = None
    audience_value: float | None = None
    temporary_trend_dependency: float | None = None
    reason: str


class OpportunityCandidate(BaseModel):
    candidate_id: str
    topic: str
    proposed_title: str | None = None
    angle: str | None = None
    why_interesting: str | None = None
    curiosity_hook: str | None = None
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
    discovery_sources: list[str] = Field(default_factory=list)
    competitor_topic_performance_available: bool = False
    competitor_evidence: list[CompetitorEvidence] = Field(default_factory=list)
    competitor_topic_patterns: list[CompetitorTopicPattern] = Field(default_factory=list)
    ritzz_differentiation_angle: str | None = None
    observed_pattern: str | None = None
    concrete_subject: str | None = None
    subject_evidence_refs: list[str] = Field(default_factory=list)
    originality_reason: str | None = None
    curiosity_family: str | None = None
    current_vidiq_demand_signals: dict[str, EvidenceMetric] = Field(default_factory=dict)
    current_vidiq_demand_available: bool = False
    vidiq_status: Literal["SCORED", "UNAVAILABLE"] = "UNAVAILABLE"
    competition_saturation_signal: EvidenceMetric | None = None
    competition_saturation_assessment: str | None = None
    inventory_status: str | None = None
    ritzz_fit: RitzzFitResult | None = None
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
    discovery_diagnostics: dict[str, Any] = Field(default_factory=dict)


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
    normalized_topic: str | None = None
    angle: str | None = None
    source_evidence: dict[str, Any] = Field(default_factory=dict)
    trend_evidence: dict[str, Any] = Field(default_factory=dict)
    competitor_evidence: list[dict[str, Any]] = Field(default_factory=list)
    ritzz_fit: dict[str, Any] | None = None
    ritzz_learning_signals: dict[str, Any] | None = None
    approval_metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_duration(self):
        if self.minimum_duration_seconds > self.target_duration_seconds:
            raise ValueError("minimum_duration_seconds cannot exceed target_duration_seconds")
        return self
