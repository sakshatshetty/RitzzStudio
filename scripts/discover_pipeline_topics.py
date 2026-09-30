"""Discover four pipeline candidates without interactive terminal input."""

import hashlib
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.topic_intelligence.engine import TopicIntelligenceEngine
from modules.topic_intelligence.inventory import (
    ContentInventoryManager,
    normalize_topic,
)
from modules.topic_intelligence.models import (
    OpportunityCandidate,
    OpportunityReport,
    TopicDiscoveryRequest,
)


def _candidate_markdown(index: int, candidate) -> str:
    score = (
        f"{candidate.opportunity_score:.1f}/100"
        if candidate.opportunity_score is not None
        else "unscored"
    )
    rationale = "; ".join(candidate.rationale[:2]) or "No additional rationale recorded."
    demand_signals = "; ".join(
        f"{name}: {metric.value} ({metric.source})"
        for name, metric in candidate.current_vidiq_demand_signals.items()
        if metric.available and metric.value is not None
    ) or "No current demand/trend metric available."
    competition = candidate.competition_saturation_signal
    competition_summary = (
        f"{competition.value} {competition.unit or ''} ({competition.source})".strip()
        if competition and competition.available and competition.value is not None
        else "No current competition metric available."
    )
    competitor_lines = []
    for evidence in candidate.competitor_evidence[:3]:
        observed = ", ".join(
            f"{name}={value}" for name, value in evidence.observed_performance.items()
        ) or "performance metrics unavailable"
        baseline = ", ".join(
            f"{name}={value}" for name, value in evidence.baseline.items()
        ) or "baseline unavailable"
        signal = evidence.outlier_signal.get("classification", "not established")
        competitor_lines.append(
            f"  - {evidence.channel.get('name') or evidence.channel.get('id') or 'Unknown channel'}: "
            f"{evidence.video.get('title') or 'Untitled video'} "
            f"(topic: {evidence.topic or 'not provided'}; observed: {observed}; "
            f"baseline: {baseline}; outlier signal: {signal}; source: {evidence.source}; "
            f"collected: {evidence.collected_at})"
        )
    competitor_summary = (
        "\n".join(competitor_lines)
        if competitor_lines
        else "  - No relevant competitor-video records matched this topic."
    )
    pattern_summary = "; ".join(
        f"{pattern.topic}: {pattern.video_count} videos across "
        f"{pattern.channel_count} channels"
        for pattern in candidate.competitor_topic_patterns
    ) or "No repeated competitor-topic pattern matched this candidate."
    return (
        f"### {index}. {candidate.proposed_title or candidate.topic}\n"
        f"- VidIQ topic signal: {candidate.topic}\n"
        f"- Candidate ID: `{candidate.candidate_id}`\n"
        f"- Type: `{candidate.opportunity_type}`\n"
        f"- Opportunity score: `{score}`\n"
        f"- Editorial fit: `{candidate.editorial_status or 'REVIEW'}`\n"
        f"- Evidence status: `{candidate.validation_status}`\n"
        f"- Explainer angle: {candidate.angle or 'Not provided.'}\n"
        f"- Why it is interesting: {candidate.why_interesting or 'Not provided.'}\n"
        f"- Current vidIQ demand/trend: {demand_signals}\n"
        f"- Current vidIQ competition/saturation: {competition_summary}\n"
        f"- Competition/saturation interpretation: "
        f"{candidate.competition_saturation_assessment or 'Not assessed.'}\n"
        f"- RITZZ differentiation angle: {candidate.ritzz_differentiation_angle or 'Not provided.'}\n"
        f"- Competitor video performance available: "
        f"`{str(candidate.competitor_topic_performance_available).lower()}`\n"
        f"- Repeated competitor topic patterns: {pattern_summary}\n"
        f"- Relevant competitor evidence:\n{competitor_summary}\n"
        f"- Notes: {rationale}\n"
    )


def discover_four_candidates(
    engine: TopicIntelligenceEngine,
    request: TopicDiscoveryRequest,
) -> tuple[OpportunityReport, list[OpportunityCandidate], list[str]]:
    report = engine.discover(request)
    candidates: list[OpportunityCandidate] = []
    seen_topics: set[str] = set()
    seen_ids: set[str] = set()

    def add_distinct(items: list[OpportunityCandidate]) -> None:
        for candidate in items:
            if (
                candidate.editorial_status != "PASS"
                or candidate.filter_reasons
                or any("near-duplicate" in reason.casefold() for reason in candidate.validation_reasons)
            ):
                continue
            key = normalize_topic(candidate.topic)
            if key and key not in seen_topics:
                seen_topics.add(key)
                if candidate.candidate_id in seen_ids:
                    suffix = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
                    candidate = candidate.model_copy(
                        update={"candidate_id": f"{candidate.candidate_id}_{suffix}"}
                    )
                seen_ids.add(candidate.candidate_id)
                candidates.append(candidate)

    add_distinct(report.candidates)
    discovery_notes = [f"{request.trend_topic or 'unscoped'}: {len(candidates)} distinct candidate(s)"]

    if len(candidates) < 4 and request.mode == "TRENDING" and request.trend_topic:
        broader_request = request.model_copy(update={"trend_topic": None, "force_refresh": True})
        broader_report = engine.discover(broader_request)
        add_distinct(broader_report.candidates)
        report = broader_report
        discovery_notes.append(f"unscoped fallback: {len(candidates)} distinct candidate(s) total")
        report.warnings.insert(
            0,
            f"The '{request.trend_topic}' category returned fewer than four unique candidates; unscoped trending results were added.",
        )

    report.candidates = candidates[:4]
    report.shortlist_candidate_ids = [
        candidate.candidate_id
        for candidate in report.candidates
    ]
    if len(report.candidates) < 4:
        warning_text = "; ".join(report.warnings)
        raise RuntimeError(
            f"vidIQ returned only {len(report.candidates)} distinct candidates after fallback discovery; four are required. "
            f"Discovery details: {'; '.join(discovery_notes)}. {warning_text}"
        )
    return report, report.candidates, discovery_notes


def main() -> int:
    output_directory = Path(os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts"))
    output_directory.mkdir(parents=True, exist_ok=True)

    mode = os.environ.get("RITZZ_DISCOVERY_MODE", "TRENDING").upper()
    if mode == "TRENDING":
        discovery_mode = "TRENDING"
    elif mode == "EVERGREEN":
        discovery_mode = "EVERGREEN"
    else:
        raise ValueError(f"Unsupported topic discovery mode: {mode!r}.")
    timeframe = os.environ.get("RITZZ_DISCOVERY_TIMEFRAME", "this week")
    trend_topic = os.environ.get("RITZZ_TREND_TOPIC") or None
    inventory_file = Path(
        os.environ.get("RITZZ_INVENTORY_FILE", "data/content_inventory.json")
    )
    engine = TopicIntelligenceEngine(
        inventory_manager=ContentInventoryManager(inventory_file),
    )
    report, candidates, discovery_notes = discover_four_candidates(
        engine,
        TopicDiscoveryRequest(
            mode=discovery_mode,
            timeframe=timeframe,
            trend_topic=trend_topic,
            force_refresh=True,
            pipeline_topic_gate=True,
        ),
    )

    payload = {
        "report_id": report.report_id,
        "created_at": report.created_at,
        "provider": report.provider,
        "request": report.request.model_dump(mode="json"),
        "discovery_notes": discovery_notes,
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }
    candidates_file = output_directory / "topic_candidates.json"
    candidates_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "## RITZZ topic approval required",
        "",
        "Reply to the pipeline approval issue with exactly `1`, `2`, `3`, or `4`.",
        "The selected candidate will be persisted before production continues.",
        "",
        "Discovery: " + "; ".join(discovery_notes),
        "",
    ]
    lines.extend(_candidate_markdown(index, candidate) for index, candidate in enumerate(candidates, start=1))
    summary = "\n".join(lines) + "\n"
    summary_file = output_directory / "topic_candidates.md"
    summary_file.write_text(summary, encoding="utf-8")

    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with Path(github_summary).open("a", encoding="utf-8") as stream:
            stream.write(summary)

    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
