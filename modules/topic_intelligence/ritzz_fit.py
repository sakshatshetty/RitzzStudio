"""Cheap RITZZ-fit prefilter and explicit fit-result construction."""

import re

from modules.topic_intelligence.models import (
    OpportunityCandidate,
    RitzzFitResult,
    RitzzFitStatus,
    StoryType,
)

_REJECT_PATTERNS = (
    (re.compile(r"\b[\w'’ -]+\s+vs\.?\s+[\w'’ -]+\b", re.IGNORECASE), "live sports or event matchup"),
    (re.compile(r"\b(trailer|teaser|official video|song release|lyrics)\b", re.IGNORECASE), "promotional entertainment query"),
    (re.compile(r"\b(breaking news|live updates|latest news|match today)\b", re.IGNORECASE), "temporary news or live event"),
)
_AMBIGUOUS_ENTITY = re.compile(r"^[A-Za-z][A-Za-z0-9.'’-]*$")
_AMBIGUOUS_SUFFIX = re.compile(r"\b(?:ph|official|status)\b", re.IGNORECASE)


def prefilter_reason(candidate: OpportunityCandidate) -> tuple[RitzzFitStatus, str] | None:
    """Return a cheap hard exclusion or ambiguity hold without calling an LLM."""
    topic = candidate.topic.strip()
    for pattern, reason in _REJECT_PATTERNS:
        if pattern.search(topic):
            return "FAIL", f"RITZZ-fit prefilter rejected a {reason}: {topic}."
    if _AMBIGUOUS_ENTITY.fullmatch(topic) or _AMBIGUOUS_SUFFIX.search(topic):
        return "REVIEW", "RITZZ-fit prefilter found an ambiguous entity without an explanatory question."
    return None


def build_ritzz_fit_result(
    candidate: OpportunityCandidate,
    *,
    story_type: StoryType = "OTHER",
    editorial_status: str | None = None,
    editorial_scores: dict[str, float] | None = None,
    pass_threshold: float = 65.0,
) -> RitzzFitResult:
    """Build a transparent fit assessment from editorial scores and hard gates."""
    scores = editorial_scores or {}
    curiosity = scores.get("curiosity")
    researchability = scores.get("researchability")
    story_depth = scores.get("story_depth")
    originality = scores.get("originality", scores.get("differentiation"))
    visual = scores.get("visual")
    evergreen = scores.get("evergreen")
    audience = scores.get("audience_fit")
    score_values = [
        value
        for value in (
            curiosity,
            researchability,
            story_depth,
            originality,
            visual,
            evergreen,
            audience,
        )
        if value is not None
    ]
    fit_score = round(sum(score_values) / len(score_values), 1) if score_values else None

    prefilter = prefilter_reason(candidate)
    if prefilter is not None:
        status, reason = prefilter
    elif editorial_status == "FAIL":
        status, reason = "FAIL", "Editorial assessment rejected the topic; competitor and demand evidence cannot override this."
    elif editorial_status != "PASS":
        status, reason = "REVIEW", "Editorial assessment did not pass; RITZZ fit remains unconfirmed."
    elif fit_score is None or fit_score < pass_threshold:
        status, reason = "REVIEW", f"RITZZ-fit score is below the configured {pass_threshold:.0f} pass threshold."
    else:
        status, reason = "PASS", "Editorial PASS and the configured RITZZ-fit score threshold were both met."

    return RitzzFitResult(
        fit_status=status,
        fit_score=fit_score,
        story_type=story_type,
        curiosity_strength=curiosity,
        researchability=researchability,
        story_depth=story_depth,
        originality=originality,
        visual_potential=visual,
        evergreen_potential=evergreen,
        audience_value=audience,
        temporary_trend_dependency=scores.get(
            "temporary_trend_dependency",
            candidate.ritzz_fit.temporary_trend_dependency
            if candidate.ritzz_fit
            else None,
        ),
        reason=reason,
    )
