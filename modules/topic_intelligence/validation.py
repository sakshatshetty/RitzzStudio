"""Final eligibility checks before a topic is shown as a recommendation."""

import re

from modules.topic_intelligence.models import OpportunityCandidate

MIN_EVIDENCE_COMPLETENESS = 0.5
MIN_OPPORTUNITY_SCORE = 55.0

_UNSUITABLE_TERMS = {
    "celebrity gossip", "celebrity feud", "influencer drama", "election results",
    "political campaign", "presidential campaign", "stock price", "crypto price",
}
_BROAD_TERMS = {"united nations", "politics", "celebrity news", "breaking news"}


def apply_niche_filter(candidates: list[OpportunityCandidate]) -> None:
    """Flag obvious non-RITZZ topics without inventing a replacement score."""
    for candidate in candidates:
        topic = candidate.topic.casefold()
        if any(term in topic for term in _UNSUITABLE_TERMS):
            candidate.filter_reasons.append("Outside the mixed-curiosity explainer niche.")
        elif any(term in topic for term in _BROAD_TERMS):
            candidate.filter_reasons.append("Broad or news-adjacent topic needs a specific curiosity angle.")


def _topic_key(candidate: OpportunityCandidate) -> str:
    value = candidate.primary_keyword or candidate.topic
    words = re.findall(r"[a-z0-9]+", value.casefold())
    return " ".join(word for word in words if word not in {"a", "an", "the"})


def validate_candidates(candidates: list[OpportunityCandidate]) -> list[str]:
    """Annotate candidates and return IDs that pass the recommendation gate.

    Candidates remain in the report even when rejected or held for review so the
    user can inspect the provider evidence and make an informed exception.
    """
    recommended_ids: list[str] = []
    seen: dict[str, OpportunityCandidate] = {}
    for candidate in candidates:
        candidate.validation_status = "RECOMMENDED"
        candidate.validation_reasons = []
        key = _topic_key(candidate)
        previous = seen.get(key)
        if previous is not None:
            candidate.validation_status = "REVIEW"
            candidate.validation_reasons.append(
                f"Near-duplicate of '{previous.topic}'; compare both angles before selecting."
            )
        else:
            seen[key] = candidate

        if candidate.editorial_status == "FAIL":
            candidate.validation_status = "REJECTED"
            candidate.validation_reasons.append("Editorial assessment marked this topic unsuitable.")
        elif candidate.editorial_status == "REVIEW":
            candidate.validation_status = "REVIEW"
            candidate.validation_reasons.append("Editorial fit requires human review.")
        if candidate.filter_reasons:
            candidate.validation_status = "REVIEW"
            candidate.validation_reasons.append("Niche-fit concerns require human review.")
        if candidate.score_completeness < MIN_EVIDENCE_COMPLETENESS:
            candidate.validation_status = "REVIEW"
            candidate.validation_reasons.append(
                f"Evidence completeness is below {MIN_EVIDENCE_COMPLETENESS:.0%}."
            )
        if candidate.opportunity_score is None:
            candidate.validation_status = "REVIEW"
            candidate.validation_reasons.append("No comparable opportunity score was calculated.")
        elif candidate.opportunity_score < MIN_OPPORTUNITY_SCORE:
            candidate.validation_status = "REVIEW"
            candidate.validation_reasons.append(
                f"Opportunity score is below the {MIN_OPPORTUNITY_SCORE:.0f} recommendation threshold."
            )
        if candidate.validation_status == "RECOMMENDED":
            recommended_ids.append(candidate.candidate_id)
    return recommended_ids