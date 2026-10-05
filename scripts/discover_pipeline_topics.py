"""Discover pipeline candidates without interactive terminal input."""

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Literal, Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.topic_intelligence.competitor_opportunities import (
    CompetitorOpportunityGenerator,
)
from modules.topic_intelligence.engine import (
    CompetitorPipelineDiscoveryError,
    TopicIntelligenceEngine,
)
from modules.topic_intelligence.inventory import (
    ContentInventoryManager,
    normalize_topic,
)
from modules.topic_intelligence.models import (
    OpportunityCandidate,
    OpportunityReport,
    TopicDiscoveryRequest,
)


class TopicDiscoveryEngine(Protocol):
    def discover(self, request: TopicDiscoveryRequest) -> OpportunityReport: ...


def _candidate_markdown(index: int, candidate) -> str:
    score = (
        f"{candidate.opportunity_score:.1f}/100"
        if candidate.opportunity_score is not None
        else "unscored"
    )
    rationale = "; ".join(candidate.rationale[:2]) or "No additional rationale recorded."
    metrics = [
        f"{name}: {metric.value} {metric.unit or ''}".strip()
        for name, metric in candidate.current_vidiq_demand_signals.items()
        if metric.available and metric.value is not None
    ]
    outlier_lines = []
    for evidence in candidate.competitor_evidence[:3]:
        video = evidence.video
        performance = evidence.observed_performance
        signal = evidence.outlier_signal
        details = [video.get("title") or "Untitled competitor video"]
        channel = evidence.channel.get("name")
        if channel:
            details.append(f"channel: {channel}")
        if performance.get("views") is not None:
            details.append(f"views: {performance['views']}")
        if video.get("age_days") is not None:
            details.append(f"age: {video['age_days']} days")
        if signal.get("ratio") is not None:
            details.append(f"channel baseline multiple: {signal['ratio']}x")
        elif performance.get("breakout_score") is not None:
            details.append(f"vidIQ breakout score: {performance['breakout_score']}")
        if evidence.baseline.get("views") is not None:
            details.append(f"baseline: {evidence.baseline['views']} views")
        outlier_lines.append("- Outlier inspiration: " + "; ".join(map(str, details)))
    inspiration = "\n".join(outlier_lines) or "- Outlier inspiration: unavailable"
    return (
        f"### {index}. {candidate.proposed_title or candidate.topic}\n"
        f"- Proposed topic: {candidate.topic}\n"
        f"- Candidate ID: `{candidate.candidate_id}`\n"
        f"- Type: `{candidate.opportunity_type}`\n"
        f"- Opportunity score: `{score}`\n"
        f"- Editorial fit: `{candidate.editorial_status or 'REVIEW'}`\n"
        f"- Evidence status: `{candidate.validation_status}`\n"
        f"- Explainer angle: {candidate.angle or 'Not provided.'}\n"
        f"- Curiosity hook: {candidate.curiosity_hook or candidate.why_interesting or 'Not provided.'}\n"
        f"- Original RITZZ angle: {candidate.ritzz_differentiation_angle or 'Not provided.'}\n"
        f"{inspiration}\n"
        f"- vidIQ validation: {'; '.join(metrics) if metrics else 'No usable metrics.'}\n"
        f"- Inventory status: {candidate.inventory_status or 'Not recorded'}\n"
        f"- Notes: {rationale}\n"
    )


def discover_four_candidates(
    engine: TopicDiscoveryEngine,
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
                or candidate.validation_status != "RECOMMENDED"
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
    discovery_notes = [
        (
            f"{request.trend_topic or request.niche}: {len(candidates)} distinct "
            "competitor-inspired candidate(s); no fallback discovery was run"
        )
    ]

    report.candidates = candidates[:5]
    report.shortlist_candidate_ids = [
        candidate.candidate_id
        for candidate in report.candidates
    ]
    if len(report.candidates) < 2:
        warning_text = "; ".join(report.warnings)
        raise CompetitorPipelineDiscoveryError(
            f"Only {len(report.candidates)} distinct candidates passed competitor and vidIQ validation; at least two are required. "
            f"Discovery details: {'; '.join(discovery_notes)}. {warning_text}",
            report.discovery_diagnostics,
        )
    return report, report.candidates, discovery_notes


def main() -> int:
    output_directory = Path(os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts"))
    output_directory.mkdir(parents=True, exist_ok=True)

    mode_value = os.environ.get("RITZZ_DISCOVERY_MODE", "TRENDING").upper()
    if mode_value == "TRENDING":
        mode: Literal["TRENDING", "EVERGREEN"] = "TRENDING"
    elif mode_value == "EVERGREEN":
        mode = "EVERGREEN"
    else:
        raise ValueError(f"Unsupported discovery mode: {mode_value}")
    timeframe = os.environ.get("RITZZ_DISCOVERY_TIMEFRAME", "this week")
    trend_topic = os.environ.get("RITZZ_TREND_TOPIC") or None
    inventory_file = Path(
        os.environ.get("RITZZ_INVENTORY_FILE", "data/content_inventory.json")
    )
    diagnostics_file = output_directory / "topic_discovery_diagnostics.json"
    try:
        engine = TopicIntelligenceEngine(
            inventory_manager=ContentInventoryManager(inventory_file),
            competitor_opportunity_generator=CompetitorOpportunityGenerator(),
        )
        report, candidates, discovery_notes = discover_four_candidates(
            engine,
            TopicDiscoveryRequest(
                mode=mode,
                timeframe=timeframe,
                trend_topic=trend_topic,
                force_refresh=True,
                pipeline_topic_gate=True,
            ),
        )
    except Exception as exc:
        diagnostics = (
            exc.diagnostics
            if isinstance(exc, CompetitorPipelineDiscoveryError)
            else {"status": "FAILED", "error": str(exc)}
        )
        diagnostics_file.write_text(
            json.dumps(diagnostics, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise

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
    diagnostics_file.write_text(
        json.dumps(report.discovery_diagnostics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "## RITZZ topic approval required",
        "",
        f"Reply to the pipeline approval issue with exactly one number from `1` to `{len(candidates)}`.",
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
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as stream:
            stream.write(f"candidate_count={len(candidates)}\n")

    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
