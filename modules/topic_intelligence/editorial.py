"""Evidence-grounded editorial scoring for RITZZ topic candidates."""

import json
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.topic_intelligence.models import OpportunityCandidate


class CandidateEditorialAssessment(BaseModel):
    candidate_id: str
    proposed_title: str = ""
    angle: str = ""
    why_interesting: str = ""
    audience_fit: float = Field(ge=0, le=100)
    curiosity: float = Field(ge=0, le=100)
    evergreen: float = Field(ge=0, le=100)
    visual: float = Field(ge=0, le=100)
    researchability: float = Field(ge=0, le=100)
    differentiation: float = Field(ge=0, le=100)
    saturation: float = Field(ge=0, le=100, description="100 means little existing-content saturation")
    status: Literal["PASS", "REVIEW", "FAIL"]
    rationale: list[str] = Field(default_factory=list)
    filter_reasons: list[str] = Field(default_factory=list)


class CandidateEditorialAssessments(BaseModel):
    assessments: list[CandidateEditorialAssessment]


class EditorialEvaluator:
    """Use the configured OpenAI model for preliminary editorial judgment only."""

    prompt_version = "ritzz-editorial-assessment-v1"

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
            "Return exactly one assessment for every candidate ID. Score audience fit, "
            "curiosity, evergreen potential, visual storytelling, researchability, "
            "differentiation, and low saturation from 0 to 100. A higher saturation "
            "score means less saturated. Use only the topic and supplied evidence; "
            "do not invent search metrics, facts, or competitor counts. These are "
            "preliminary editorial judgments, not factual research. Mark PASS for a "
            "clear general-audience curiosity explainer, REVIEW for uncertain fit or "
            "evidence, and FAIL for clearly unsuitable ideas such as gossip, unsafe "
            "topics, or political commentary without a curiosity-explainer angle. "
            "For every candidate also provide a proposed YouTube title, a distinct explanatory angle, "
            "and one concise reason it is interesting. Explain each judgment briefly and list exclusion concerns."
        )

    @staticmethod
    def _user_prompt(candidates: list[OpportunityCandidate]) -> str:
        rows = []
        for candidate in candidates:
            rows.append({
                "candidate_id": candidate.candidate_id,
                "topic": candidate.topic,
                "primary_keyword": candidate.primary_keyword,
                "related_keywords": candidate.related_keywords,
                "related_questions": candidate.related_questions,
                "opportunity_type": candidate.opportunity_type,
                "provider_evidence": {
                    key: metric.model_dump()
                    for key, metric in candidate.evidence.items()
                },
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
            "researchability": assessment.researchability,
            "differentiation": assessment.differentiation,
            "saturation": assessment.saturation,
        }
        candidate.editorial_status = assessment.status
        candidate.proposed_title = assessment.proposed_title or candidate.topic
        candidate.angle = assessment.angle or (candidate.rationale[0] if candidate.rationale else candidate.topic)
        candidate.why_interesting = assessment.why_interesting or candidate.rationale[0] if candidate.rationale else candidate.topic
        candidate.filter_reasons = list(dict.fromkeys(candidate.filter_reasons + assessment.filter_reasons))
        candidate.rationale = list(dict.fromkeys(candidate.rationale + assessment.rationale))
    return candidates
