"""Evidence-grounded editorial scoring for RITZZ topic candidates."""

import json
import re
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.topic_intelligence.models import (
    OpportunityCandidate,
    RitzzFitResult,
    StoryType,
)

_INFORMATIONAL_FILTER_REASONS = {
    "none",
    "none significant",
    "none significant from the supplied data",
    "no significant concerns",
    "no filter reasons",
}


class CandidateEditorialAssessment(BaseModel):
    candidate_id: str
    proposed_title: str = ""
    angle: str = ""
    why_interesting: str = ""
    audience_fit: float = Field(ge=0, le=100)
    curiosity: float = Field(ge=0, le=100)
    evergreen: float = Field(ge=0, le=100)
    visual: float = Field(ge=0, le=100)
    format_fit: float = Field(ge=0, le=100)
    researchability: float = Field(ge=0, le=100)
    differentiation: float = Field(ge=0, le=100)
    saturation: float = Field(ge=0, le=100, description="100 means little existing-content saturation")
    story_depth: float = Field(default=50, ge=0, le=100)
    originality: float = Field(default=50, ge=0, le=100)
    story_type: StoryType = "OTHER"
    temporary_trend_dependency: float = Field(default=50, ge=0, le=100)
    status: Literal["PASS", "REVIEW", "FAIL"]
    rationale: list[str] = Field(default_factory=list)
    filter_reasons: list[str] = Field(default_factory=list)


class CandidateEditorialAssessments(BaseModel):
    assessments: list[CandidateEditorialAssessment]


class EditorialEvaluator:
    """Use the configured OpenAI model for preliminary editorial judgment only."""

    prompt_version = "ritzz-editorial-assessment-v3"

    def __init__(self, client=None) -> None:
        self.client = client or OpenAI(api_key=OPENAI_API_KEY)
        self.model_name = OPENAI_MODEL

    def assess(self, candidates: list[OpportunityCandidate]) -> list[CandidateEditorialAssessment]:
        response = self.client.responses.parse(
            model=self.model_name,
            input=[
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": self._user_prompt(candidates)},
            ],
            text_format=CandidateEditorialAssessments,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned no structured topic assessments.")
        expected = {candidate.candidate_id for candidate in candidates}
        found = {assessment.candidate_id for assessment in parsed.assessments}
        if found != expected:
            missing = sorted(expected - found)
            unexpected = sorted(found - expected)
            raise ValueError(
                f"Editorial assessment candidate mismatch; missing={missing}, unexpected={unexpected}."
            )
        return parsed.assessments

    @staticmethod
    def _system_prompt() -> str:
        return (
            "Assess video-topic ideas for the RITZZ mixed-curiosity YouTube channel. "
            "RITZZ publishes curiosity-led explainers, not generic reviews, recaps, reactions, or broad news summaries. "
            "A broad entity or institution is not automatically a suitable topic; it needs a specific explanatory question or mystery. "
            "Return exactly one assessment for every candidate ID. Score audience fit, "
            "curiosity, evergreen potential, visual storytelling, researchability, "
            "RITZZ visual-format fit, differentiation, and low saturation from 0 to 100. "
            "Assess format_fit specifically for an 8-minute curiosity explainer made "
            "with static 2D stickman/cartoon illustrations, hard cuts, simple symbolic "
            "props, maps and diagrams, and occasional one-word uppercase editorial "
            "callouts. No footage, pan, zoom, camera movement, or transitions are available. "
            "A low format_fit means the idea fundamentally depends on footage/action that "
            "cannot be convincingly explained through those static illustrations; score "
            "below 55 must not receive PASS. Prefer topics with strong visual explanations. "
            "A higher saturation "
            "score means less saturated. Use only the topic and supplied evidence; "
            "classify story_type and score temporary_trend_dependency from 0 "
            "(not trend-dependent) to 100 (entirely dependent on a temporary trend). "
            "Explicitly assess story depth and originality as separate 0-100 scores. "
            "For competitor-derived ideas, originality means a genuinely new question "
            "or mechanism, not a synonym-swapped competitor title. "
            "Do not invent search metrics, facts, or competitor counts. These are "
            "preliminary editorial judgments, not factual research. Mark PASS for a "
            "clear general-audience curiosity explainer, REVIEW for uncertain fit or "
            "evidence, and FAIL for clearly unsuitable ideas such as gossip, unsafe "
            "topics, or political commentary without a curiosity-explainer angle. "
            "Mark generic movie/TV reviews, recaps, reaction videos, and broad news topics FAIL unless the topic is explicitly reframed around a factual curiosity question. "
            "For every candidate also provide a proposed YouTube title, a distinct explanatory angle, "
            "and one concise reason it is interesting. Reject or mark REVIEW any abstract essay premise "
            "that does not identify an exact subject, event, place, object, person, or phenomenon. "
            "For competitor-derived candidates, check the concrete subject and subject evidence references; "
            "do not treat competitor success as proof of factual accuracy or originality. "
            "Explain each judgment briefly and list exclusion concerns."
        )

    @staticmethod
    def _user_prompt(candidates: list[OpportunityCandidate]) -> str:
        rows = []
        for candidate in candidates:
            rows.append({
                "candidate_id": candidate.candidate_id,
                "topic": candidate.topic,
                "angle": candidate.angle,
                "concrete_subject": candidate.concrete_subject,
                "subject_evidence_refs": candidate.subject_evidence_refs,
                "originality_reason": candidate.originality_reason,
                "curiosity_family": candidate.curiosity_family,
                "primary_keyword": candidate.primary_keyword,
                "related_keywords": candidate.related_keywords,
                "related_questions": candidate.related_questions,
                "discovery_sources": candidate.discovery_sources,
                "opportunity_type": candidate.opportunity_type,
                "provider_evidence": {
                    key: metric.model_dump()
                    for key, metric in candidate.evidence.items()
                },
                "competitor_evidence": [
                    evidence.model_dump(mode="json")
                    for evidence in candidate.competitor_evidence
                ],
                "competitor_topic_patterns": [
                    pattern.model_dump(mode="json")
                    for pattern in candidate.competitor_topic_patterns
                ],
                "current_vidiq_demand_signals": {
                    key: metric.model_dump()
                    for key, metric in candidate.current_vidiq_demand_signals.items()
                },
                "current_vidiq_demand_available": candidate.current_vidiq_demand_available,
                "competition_saturation_assessment": candidate.competition_saturation_assessment,
                "ritzz_fit_prefilter": (
                    candidate.ritzz_fit.model_dump(mode="json")
                    if candidate.ritzz_fit
                    else None
                ),
                "ritzz_learning_signals": candidate.ritzz_learning_signals,
            })
        return "Score these candidate ideas. Treat provider metrics as supplied data, not as proof of factual accuracy.\n" + json.dumps(rows, ensure_ascii=False)


def apply_editorial_assessments(
    candidates: list[OpportunityCandidate],
    assessments: list[CandidateEditorialAssessment],
) -> list[OpportunityCandidate]:
    by_id = {assessment.candidate_id: assessment for assessment in assessments}
    for candidate in candidates:
        assessment = by_id.get(candidate.candidate_id)
        if assessment is None:
            continue
        candidate.editorial_scores = {
            "audience_fit": assessment.audience_fit,
            "curiosity": assessment.curiosity,
            "evergreen": assessment.evergreen,
            "visual": assessment.visual,
            "format_fit": assessment.format_fit,
            "researchability": assessment.researchability,
            "differentiation": assessment.differentiation,
            "saturation": assessment.saturation,
            "story_depth": assessment.story_depth,
            "originality": assessment.originality,
        }
        candidate.editorial_status = assessment.status
        if candidate.ritzz_fit is None:
            candidate.ritzz_fit = RitzzFitResult(
                fit_status="REVIEW",
                reason="Editorial assessment completed; RITZZ fit not finalized.",
            )
        candidate.ritzz_fit.story_type = assessment.story_type
        candidate.ritzz_fit.temporary_trend_dependency = (
            assessment.temporary_trend_dependency
        )
        candidate.proposed_title = assessment.proposed_title or candidate.topic
        candidate.angle = assessment.angle or (candidate.rationale[0] if candidate.rationale else candidate.topic)
        candidate.why_interesting = assessment.why_interesting or candidate.rationale[0] if candidate.rationale else candidate.topic
        filter_reasons = [
            reason.strip()
            for reason in candidate.filter_reasons + assessment.filter_reasons
            if re.sub(r"[^a-z0-9 ]", "", reason.casefold()).strip()
            not in _INFORMATIONAL_FILTER_REASONS
        ]
        candidate.filter_reasons = list(dict.fromkeys(filter_reasons))
        candidate.rationale = list(dict.fromkeys(candidate.rationale + assessment.rationale))
    return candidates
