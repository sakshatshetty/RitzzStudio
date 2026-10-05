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
_CURRENT_EVENT_DISASTER = re.compile(
    r"\b(?:current|recent|latest|today|yesterday|this week|this month|breaking)\b"
    r".{0,60}\b(?:flood|earthquake|wildfire|hurricane|storm|disaster|landslide|"
    r"tsunami|eruption|crash)\b"
    r"|\b(?:nepal flood|current disaster|recent disaster)\b",
    re.IGNORECASE,
)
_SPORTS_TOPIC = re.compile(
    r"\b(?:sports?|championship|league|match|game|tournament|world cup|"
    r"football|basketball|cricket|baseball|tennis|formula one|f1)\b",
    re.IGNORECASE,
)
_HISTORICAL_CONTEXT = re.compile(
    r"\b(?:ancient|prehistoric|prehistory|paleolithic|palaeolithic|neolithic|"
    r"mesolithic|stone age|bronze age|iron age|early humans?|hunter.gatherers?|"
    r"neanderthals?|homo sapiens|human species|human evolution|roman|egypt(?:ian)?|"
    r"mesopotamian|sumerian|babylonian|assyrian|greek|maya|aztec|inca|"
    r"minoan|mycenaean|persian|viking|medieval|byzantine|han dynasty|"
    r"historical|history)\b",
    re.IGNORECASE,
)
_BROAD_HISTORY_TOPICS = {
    "ancient history",
    "history",
    "history of egypt",
    "ancient civilizations",
    "ancient civilization",
    "ancient mysteries",
    "ancient human survival",
    "ancient engineering",
    "ancient cities",
    "ancient archaeology",
    "ancient inventions",
    "ancient technology",
    "roman aqueducts",
    "broad archaeology",
    "archaeology",
}
_BROAD_HISTORY_PREFIX = re.compile(
    r"^(?:the )?history of (?:ancient )?[a-z][a-z -]{1,40}$",
    re.IGNORECASE,
)


def apply_niche_filter(candidates: list[OpportunityCandidate]) -> None:
    """Flag off-profile and overly broad topics without inventing a score."""
    for candidate in candidates:
        topic = candidate.topic.casefold()
        if any(term in topic for term in _UNSUITABLE_TERMS):
            candidate.filter_reasons.append(
                "This is a review, recap, reaction, or otherwise unsuitable format for the curiosity-explainer channel."
            )
        elif _CURRENT_EVENT_DISASTER.search(topic):
            candidate.filter_reasons.append(
                "Current-event disasters are outside the historical human-curiosity niche."
            )
        elif _SPORTS_TOPIC.search(topic) and not _HISTORICAL_CONTEXT.search(topic):
            candidate.filter_reasons.append(
                "Modern sports and sports-news topics are outside the historical human-curiosity niche."
            )
        elif any(term in topic for term in _BROAD_TERMS):
            candidate.filter_reasons.append("Broad or news-adjacent topic needs a specific curiosity angle.")
        elif (
            topic.strip(" ?.!").casefold() in _BROAD_HISTORY_TOPICS
            or _BROAD_HISTORY_PREFIX.fullmatch(topic.strip(" ?.!"))
        ):
            candidate.filter_reasons.append(
                "Broad historical category needs a specific human-curiosity question."
            )
        elif not _HISTORICAL_CONTEXT.search(topic):
            candidate.filter_reasons.append(
                "Topic is not anchored in ancient humans, a historical period, or a specific history-curiosity question."
            )


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