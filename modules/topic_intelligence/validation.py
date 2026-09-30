"""Final eligibility checks before a topic is shown as a recommendation."""

import re

from modules.topic_intelligence.models import OpportunityCandidate

MIN_EVIDENCE_COMPLETENESS = 0.5
MIN_OPPORTUNITY_SCORE = 55.0

_UNSUITABLE_TERMS = {
    "celebrity gossip", "celebrity feud", "influencer drama", "election results",
    "political campaign", "presidential campaign", "stock price", "crypto price",
    "movie review", "film review", "movie reviews", "film reviews", "episode recap",
    "season recap", "reaction video",
}
_BROAD_TERMS = {"united nations", "politics", "celebrity news", "breaking news"}


def apply_niche_filter(candidates: list[OpportunityCandidate]) -> None:
    """Flag obvious non-RITZZ topics without inventing a replacement score."""
    for candidate in candidates:
        topic = candidate.topic.casefold()
        if any(term in topic for term in _UNSUITABLE_TERMS):
            candidate.filter_reasons.append(
                "This is a review, recap, reaction, or otherwise unsuitable format for the curiosity-explainer channel."
            )
        elif any(term in topic for term in _BROAD_TERMS):
            candidate.filter_reasons.append("Broad or news-adjacent topic needs a specific curiosity angle.")


def _topic_key(candidate: OpportunityCandidate) -> str:
    value = candidate.primary_keyword or candidate.topic
    value = re.sub(r"\b(?:pirates|sailors?)\b", "sailor", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(?:wear|wears|wearing|wore|use|uses|using|used)\b", "use", value, flags=re.IGNORECASE)
    value = re.sub(r"\beye\s+patch(?:es)?\b", "eyepatch", value, flags=re.IGNORECASE)
    words = re.findall(r"[a-z0-9]+", value.casefold())
    words = [
        word for word in words
        if word not in {"a", "an", "are", "did", "do", "does", "how", "is", "the", "why"}
    ]
    if "vs" in words or "versus" in words:
        sides = re.split(r"\b(?:vs\.?|versus)\b", value.casefold())
        if len(sides) == 2:
            left = " ".join(re.findall(r"[a-z0-9]+", sides[0]))
            right = " ".join(re.findall(r"[a-z0-9]+", sides[1]))
            return " vs ".join(sorted((left, right)))
    return " ".join(words)


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
        fit_status = candidate.ritzz_fit.fit_status if candidate.ritzz_fit else None
        if fit_status == "FAIL":
            candidate.validation_status = "REJECTED"
            candidate.validation_reasons.append(
                candidate.ritzz_fit.reason
                if candidate.ritzz_fit
                else "RITZZ-fit assessment marked this topic unsuitable."
            )
        elif fit_status == "REVIEW":
            candidate.validation_status = "REVIEW"
            candidate.validation_reasons.append(
                candidate.ritzz_fit.reason
                if candidate.ritzz_fit
                else "RITZZ-fit assessment requires review."
            )
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