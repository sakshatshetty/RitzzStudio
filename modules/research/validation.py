"""Deterministic validation of research claims before outlining."""

import re
from typing import Literal

from pydantic import BaseModel, Field

from modules.research.models import Research

ValidationStatus = Literal["PASS", "REVIEW", "FAIL"]


class ClaimValidation(BaseModel):
    claim: str
    importance: str
    status: ValidationStatus
    issues: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)


class ResearchValidationReport(BaseModel):
    topic: str
    status: ValidationStatus
    claims: list[ClaimValidation] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    source_count: int = 0
    validator_version: str = "ritzz-research-validation-v1"


def validate_research(research: Research) -> ResearchValidationReport:
    """Check source coverage, source IDs, confidence, and obvious conflicts.

    This validator does not invent facts or adjudicate disputed claims. It marks
    uncertain material for review and fails only when important claims lack
    usable evidence.
    """
    source_ids = {source.id for source in research.sources}
    results: list[ClaimValidation] = []
    report_issues: list[str] = []
    contradictions: list[str] = []

    facts = [item.fact for item in research.key_facts]
    for index, left in enumerate(facts):
        left_tokens = set(re.findall(r"[a-z0-9]+", left.casefold()))
        left_negative = bool(re.search(r"\b(?:not|never|no|without|isn't|didn't|doesn't)\b", left.casefold()))
        for right in facts[index + 1:]:
            right_tokens = set(re.findall(r"[a-z0-9]+", right.casefold()))
            right_negative = bool(re.search(r"\b(?:not|never|no|without|isn't|didn't|doesn't)\b", right.casefold()))
            union = left_tokens | right_tokens
            similarity = len(left_tokens & right_tokens) / len(union) if union else 0
            if similarity >= 0.6 and left_negative != right_negative:
                contradictions.append(f"Potential contradiction between claims: '{left}' and '{right}'.")
    if contradictions:
        report_issues.append(f"{len(contradictions)} potential contradiction(s) require review.")

    for fact in research.key_facts:
        issues: list[str] = []
        missing = [source_id for source_id in fact.sources if source_id not in source_ids]
        if not fact.sources:
            issues.append("Important claim has no source reference.")
        if missing:
            issues.append(f"Unknown source reference(s): {', '.join(missing)}.")
        if fact.confidence == "low":
            issues.append("Claim confidence is low; use cautious wording or review.")
        status: ValidationStatus = "FAIL" if fact.importance == "high" and any(
            issue.startswith("Important claim") or issue.startswith("Unknown source") for issue in issues
        ) else "REVIEW" if issues else "PASS"
        results.append(ClaimValidation(
            claim=fact.fact,
            importance=fact.importance,
            status=status,
            issues=issues,
            sources=fact.sources,
        ))

    for item in (*research.historical_context, *research.surprising_facts):
        issues = []
        if not item.sources:
            issues.append("Claim has no source reference.")
        if any(source_id not in source_ids for source_id in item.sources):
            issues.append("Claim references an unknown source.")
        results.append(ClaimValidation(
            claim=item.fact,
            importance="medium",
            status="REVIEW" if issues else "PASS",
            issues=issues,
            sources=item.sources,
        ))

    for myth in research.common_myths:
        issues = []
        if not myth.sources:
            issues.append("Myth/reality pair has no source reference.")
        if any(source_id not in source_ids for source_id in myth.sources):
            issues.append("Myth/reality pair references an unknown source.")
        results.append(ClaimValidation(
            claim=f"{myth.claim} -> {myth.reality}",
            importance="medium",
            status="REVIEW" if issues else "PASS",
            issues=issues,
            sources=myth.sources,
        ))

    low_confidence = sum(item.confidence == "low" for item in research.key_facts)
    if low_confidence:
        report_issues.append(f"{low_confidence} key claim(s) have low confidence and need cautious wording.")
    if not research.sources:
        report_issues.append("Research contains no sources.")

    if any(item.status == "FAIL" for item in results):
        status: ValidationStatus = "FAIL"
    elif any(item.status == "REVIEW" for item in results) or report_issues:
        status = "REVIEW"
    else:
        status = "PASS"
    return ResearchValidationReport(
        topic=research.topic,
        status=status,
        claims=results,
        issues=report_issues,
        contradictions=contradictions,
        source_count=len(research.sources),
    )
