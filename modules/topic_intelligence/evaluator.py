import math
import re
from statistics import median

from modules.topic_intelligence.models import OpportunityCandidate

WEIGHTS = {
    "demand": 15,
    "momentum": 15,
    "competition": 10,
    "audience_fit": 12,
    "curiosity": 10,
    "evergreen": 7,
    "visual": 8,
    "researchability": 8,
    "differentiation": 8,
    "saturation": 7,
}


def _numeric(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        return float(match.group()) if match else None
    return None


def _relative_scale(values: list[float | None], *, log_scale: bool = False) -> list[float | None]:
    present = [value for value in values if value is not None]
    if not present:
        return [None] * len(values)
    transformed = [math.log1p(max(0, value)) if log_scale and value is not None else value for value in values]
    valid = [value for value in transformed if value is not None]
    low, high = min(valid), max(valid)
    if high == low:
        return [50.0 if value is not None else None for value in transformed]
    return [round((value - low) / (high - low) * 100, 1) if value is not None else None for value in transformed]


def _competition_score(value) -> float | None:
    numeric = _numeric(value)
    if numeric is not None and 0 <= numeric <= 100:
        return round(100 - numeric, 1)
    if isinstance(value, str):
        level = value.casefold()
        if "low" in level:
            return 80.0
        if "medium" in level or "moderate" in level:
            return 50.0
        if "high" in level:
            return 20.0
    return None


def score_candidate(candidate: OpportunityCandidate) -> OpportunityCandidate:
    """Score only explicit 0-100 scores; missing components remain absent."""
    scores: dict[str, float | None] = {}
    # vidIQ's overall keyword score combines demand and competition. Keep it as
    # raw evidence; do not mislabel it as a pure demand score.
    aliases = {
        "demand": ("search_volume_score",),
        "momentum": ("growth_score", "trend_score"),
        "competition": ("competition_opportunity_score",),
        "saturation": ("saturation_score",),
    }
    for component, names in aliases.items():
        metric = next((candidate.evidence[name] for name in names if name in candidate.evidence), None)
        value = _numeric(metric.value) if metric and metric.available else None
        scores[component] = value if value is not None and 0 <= value <= 100 else None
    for component in set(WEIGHTS) - set(aliases):
        value = candidate.editorial_scores.get(component)
        scores[component] = float(value) if value is not None and 0 <= value <= 100 else None
    return _apply_scores(candidate, scores)


def _apply_scores(candidate: OpportunityCandidate, scores: dict[str, float | None]) -> OpportunityCandidate:
    available_weight = sum(WEIGHTS[key] for key, value in scores.items() if value is not None)
    candidate.score_completeness = round(available_weight / sum(WEIGHTS.values()), 3)
    candidate.opportunity_score = (
        round(sum(value * WEIGHTS[key] for key, value in scores.items() if value is not None) / available_weight, 1)
        if available_weight
        else None
    )
    missing = [f"{key.replace('_', ' ').title()} evidence unavailable" for key, value in scores.items() if value is None]
    candidate.component_scores = scores
    candidate.rationale = list(dict.fromkeys(candidate.rationale + missing))
    return candidate


def rank_candidates(candidates: list[OpportunityCandidate]) -> list[OpportunityCandidate]:
    """Normalize observed volume/growth within this report, then rank stably."""
    demand_values = []
    growth_values = []
    for candidate in candidates:
        demand = _numeric(candidate.evidence.get("search_volume").value) if candidate.evidence.get("search_volume") else None
        growth_metric = next((candidate.evidence[key] for key in ("growth", "growth_percent", "trend_growth") if key in candidate.evidence), None)
        growth = _numeric(growth_metric.value) if growth_metric and growth_metric.available else None
        demand_values.append(demand if demand is not None and demand >= 0 else None)
        growth_values.append(growth if growth is not None and growth >= 0 else None)
    demand_scores = _relative_scale(demand_values, log_scale=True)
    growth_scores = _relative_scale(growth_values, log_scale=True)
    observed_demand = [value for value in demand_values if value is not None]
    demand_floor = median(observed_demand) if observed_demand else None

    scored = []
    for index, candidate in enumerate(candidates):
        scores: dict[str, float | None] = {
            "demand": demand_scores[index],
            "momentum": (
                growth_scores[index]
                if demand_values[index] is not None
                and demand_floor is not None
                and demand_values[index] >= demand_floor
                else None
            ),
            "competition": _competition_score(candidate.evidence["competition"].value)
            if "competition" in candidate.evidence and candidate.evidence["competition"].available
            else None,
        }
        for component in set(WEIGHTS) - set(scores):
            value = candidate.editorial_scores.get(component)
            scores[component] = float(value) if value is not None and 0 <= value <= 100 else None
        scored.append(_apply_scores(candidate, scores))
    return sorted(
        scored,
        key=lambda item: (
            {"PASS": 0, "REVIEW": 1, None: 1, "FAIL": 2}.get(item.editorial_status, 1),
            item.opportunity_score is None,
            -(item.opportunity_score or 0),
            -item.score_completeness,
            item.topic.casefold(),
        ),
    )
