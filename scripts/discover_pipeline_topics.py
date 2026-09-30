"""Discover four pipeline candidates without interactive terminal input."""

import json
import os
import sys
from pathlib import Path
from typing import Any

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
    fit = candidate.ritzz_fit
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
            f"  - [{evidence.channel_group or 'group unavailable'}] "
            f"{evidence.channel.get('name') or evidence.channel.get('id') or 'Unknown channel'}: "
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
        f"{pattern.channel_count} channels "
        f"(groups: {', '.join(pattern.channel_groups) or 'not recorded'}; "
        f"confidence: {pattern.confidence})"
        for pattern in candidate.competitor_topic_patterns
    ) or "No repeated competitor-topic pattern matched this candidate."
    return (
        f"### {index}. {candidate.proposed_title or candidate.topic}\n"
        f"- VidIQ topic signal: {candidate.topic}\n"
        f"- Candidate ID: `{candidate.candidate_id}`\n"
        f"- Type: `{candidate.opportunity_type}`\n"
        f"- RITZZ inventory: `{candidate.inventory_status}`\n"
        f"- Editorial fit: `{candidate.editorial_status or 'REVIEW'}`\n"
        f"- Evidence status: `{candidate.validation_status}`\n"
        f"- Explainer angle: {candidate.angle or 'Not provided.'}\n"
        f"- Concrete subject: {candidate.concrete_subject or 'Not separately recorded.'}\n"
        f"- Subject evidence references: "
        f"{', '.join(candidate.subject_evidence_refs) or 'not recorded'}\n"
        f"- Curiosity family: {candidate.curiosity_family or 'not classified'}\n"
        f"- Why it is interesting: {candidate.why_interesting or 'Not provided.'}\n"
        f"- Current vidIQ demand/trend signals available: "
        f"`{str(candidate.current_vidiq_demand_available).lower()}`\n"
        f"- Current vidIQ demand/trend: {demand_signals}\n"
        f"- Current vidIQ competition/saturation: {competition_summary}\n"
        f"- Competition/saturation interpretation: "
        f"{candidate.competition_saturation_assessment or 'Not assessed.'}\n"
        f"- RITZZ differentiation angle: {candidate.ritzz_differentiation_angle or 'Not provided.'}\n"
        f"- Why this is not a copy: {candidate.originality_reason or 'Not recorded.'}\n"
        f"- RITZZ fit: `{fit.fit_status if fit else 'REVIEW'}` "
        f"({fit.reason if fit else 'Not assessed.'})\n"
        f"- RITZZ static visual-format fit: "
        f"`{fit.format_fit if fit and fit.format_fit is not None else 'not scored'}`\n"
        f"- RITZZ historical evidence: `{candidate.ritzz_learning_signals.get('sample_size', 'INSUFFICIENT')}` "
        f"sample; {len(candidate.ritzz_learning_signals.get('topic_signals', []))} matching historical topic record(s).\n"
        f"- Competitor video performance available: "
        f"`{str(candidate.competitor_topic_performance_available).lower()}`\n"
        f"- Repeated competitor topic patterns: {pattern_summary}\n"
        f"- Relevant competitor evidence:\n{competitor_summary}\n"
        f"- Notes: {rationale}\n"
    )


class InsufficientTopicCandidatesError(RuntimeError):
    def __init__(self, message: str, diagnostics: dict[str, Any]):
        super().__init__(message)
        self.diagnostics = diagnostics


def discover_four_candidates(
    engine: TopicIntelligenceEngine,
    request: TopicDiscoveryRequest,
) -> tuple[OpportunityReport, list[OpportunityCandidate], list[str]]:
    report = engine.discover(request)
    candidates: list[OpportunityCandidate] = []
    seen_topics: set[str] = set()
    for candidate in report.candidates:
        if (
            candidate.editorial_status != "PASS"
            or candidate.ritzz_fit is None
            or candidate.ritzz_fit.fit_status != "PASS"
            or candidate.validation_status != "RECOMMENDED"
            or candidate.filter_reasons
            or any("near-duplicate" in reason.casefold() for reason in candidate.validation_reasons)
        ):
            continue
        key = normalize_topic(candidate.topic)
        if key and key not in seen_topics:
            seen_topics.add(key)
            candidates.append(candidate)

    diagnostics = report.discovery_diagnostics
    discovery_notes = [
        f"{source}: raw={counts.get('raw', 0)}, unique={counts.get('unique', 0)}"
        for source, counts in diagnostics.get("source_counts", {}).items()
    ]
    if not discovery_notes:
        discovery_notes = [f"{request.trend_topic or 'unscoped'}: {len(candidates)} eligible candidate(s)"]
    candidates.sort(key=lambda candidate: candidate.topic.casefold())
    candidates = candidates[:4]
    report.candidates = candidates
    report.shortlist_candidate_ids = [
        candidate.candidate_id
        for candidate in report.candidates
    ]
    if len(report.candidates) < 4:
        diagnostic_text = json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)
        message = (
            f"Discovery produced {len(report.candidates)} final eligible distinct candidates; four are required. "
            f"Sources attempted: {', '.join(diagnostics.get('sources_attempted', [])) or 'none'}. "
            f"Sources unavailable: {', '.join(diagnostics.get('sources_unavailable', [])) or 'none'}. "
            f"Discovery diagnostics: {diagnostic_text}. "
            f"Warnings: {'; '.join(report.warnings)}"
        )
        raise InsufficientTopicCandidatesError(message, diagnostics)
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
    try:
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
    except InsufficientTopicCandidatesError as exc:
        diagnostic_path = output_directory / "topic_discovery_diagnostics.json"
        diagnostic_path.write_text(
            json.dumps(exc.diagnostics, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        diagnostic_markdown = [
            "# Topic discovery diagnostics",
            "",
            f"- Request: `{json.dumps(exc.diagnostics.get('request', {}), ensure_ascii=False)}`",
            f"- Final eligible candidates: `{exc.diagnostics.get('final_count', 0)}` (4 required)",
            f"- Sources attempted: {', '.join(exc.diagnostics.get('sources_attempted', [])) or 'none'}",
            f"- Sources unavailable: {', '.join(exc.diagnostics.get('sources_unavailable', [])) or 'none'}",
            f"- Provider capabilities: `{json.dumps(exc.diagnostics.get('provider_capabilities', {}), ensure_ascii=False)}`",
            f"- M7 learning: `{json.dumps(exc.diagnostics.get('m7_learning', {}), ensure_ascii=False)}`",
            "",
            "## Source counts",
            "",
        ]
        for source, counts in exc.diagnostics.get("source_counts", {}).items():
            diagnostic_markdown.append(
                f"- **{source}**: raw={counts.get('raw', 0)}, unique={counts.get('unique', 0)}"
            )
        for source, duplicate_count in exc.diagnostics.get("duplicate_counts", {}).items():
            diagnostic_markdown.append(f"- **{source} duplicates removed**: {duplicate_count}")
        group_diagnostics = exc.diagnostics.get("competitor_group_diagnostics", {})
        if group_diagnostics:
            diagnostic_markdown.extend(["", "## Competitor-group evidence", ""])
            for group, counts in group_diagnostics.items():
                diagnostic_markdown.append(
                    f"- **{group}**: configured={counts.get('configured', 0)}, "
                    f"resolved={counts.get('resolved', 0)}, "
                    f"queried={counts.get('queried', 0)}, "
                    f"researched={counts.get('researched', 0)}, "
                    f"videos={counts.get('videos_inspected', 0)}, "
                    f"successful outliers={counts.get('successful_outliers', 0)}"
                )
        diagnostic_markdown.extend(["", "## Filter-stage counts", ""])
        for stage in (
            "raw_candidates",
            "after_normalization",
            "after_specificity_filter",
            "after_inventory_filter",
            "after_niche_filter",
            "after_ritzz_fit_prefilter",
            "after_visual_fit",
            "after_editorial_filter",
            "after_near_duplicate_filter",
            "after_final_validation",
            "final_count",
        ):
            if stage in exc.diagnostics:
                diagnostic_markdown.append(f"- **{stage}**: {exc.diagnostics[stage]}")
        diagnostic_markdown.extend(["", "## Candidate exclusions", ""])
        for exclusion in exc.diagnostics.get("candidate_exclusions", []):
            reasons = (
                exclusion.get("filter_reasons")
                or exclusion.get("validation_reasons")
                or [exclusion.get("ritzz_fit", {}).get("reason", "Not eligible")]
            )
            diagnostic_markdown.append(
                f"- **{exclusion.get('topic', 'Unknown')}** "
                f"[{', '.join(exclusion.get('rejection_codes', [])) or 'OTHER_HARD_FILTER'}] "
                f"(sources: {', '.join(exclusion.get('sources', [])) or 'unknown'}): "
                f"{'; '.join(str(reason) for reason in reasons)}"
            )
        for exclusion in exc.diagnostics.get("candidate_specificity_exclusions", []):
            diagnostic_markdown.append(
                f"- **{exclusion.get('topic', 'Unknown')}** "
                f"[{exclusion.get('code', 'TOO_ABSTRACT')}]: "
                f"{exclusion.get('reason', 'Candidate lacked a concrete subject.')}"
            )
        generation = exc.diagnostics.get("competitor_candidate_generation", {})
        for rejection in generation.get("candidate_rejections", []):
            diagnostic_markdown.append(
                f"- **{rejection.get('topic', 'Unknown')}** "
                f"[{rejection.get('code', 'OTHER_HARD_FILTER')}]: "
                f"{rejection.get('reason', 'Rejected during candidate generation.')}"
            )
        for exclusion in exc.diagnostics.get("inventory_exclusions", []):
            diagnostic_markdown.append(
                f"- **{exclusion.get('topic', 'Unknown')}** "
                f"[{exclusion.get('code', 'DUPLICATE')}] (inventory): "
                f"{exclusion.get('reason', 'overlap')}"
            )
        for exclusion in exc.diagnostics.get("ritzz_fit_exclusions", []):
            diagnostic_markdown.append(
                f"- **{exclusion.get('topic', 'Unknown')}** "
                f"[{exclusion.get('code', 'NOT_RITZZ_FIT')}] (RITZZ fit): "
                f"{exclusion.get('reason', 'not eligible')}"
            )
        diagnostic_markdown.extend([
            "",
            "## Recommended recovery",
            "",
            (
                "Review provider capability/source counts, broaden supported discovery sources, "
                "or revise the preferred category/timeframe. Do not lower editorial or RITZZ-fit gates."
            ),
            "",
        ])
        (output_directory / "topic_discovery_diagnostics.md").write_text(
            "\n".join(diagnostic_markdown),
            encoding="utf-8",
        )
        message = f"## Topic discovery did not find four eligible candidates\n\n{exc}\n"
        github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if github_summary:
            with Path(github_summary).open("a", encoding="utf-8") as stream:
                stream.write(message)
        print(message, file=sys.stderr)
        return 1

    payload = {
        "report_id": report.report_id,
        "created_at": report.created_at,
        "provider": report.provider,
        "request": report.request.model_dump(mode="json"),
        "discovery_notes": discovery_notes,
        "discovery_diagnostics": report.discovery_diagnostics,
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }
    candidates_file = output_directory / "topic_candidates.json"
    candidates_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    group_diagnostics = report.discovery_diagnostics.get(
        "competitor_group_diagnostics",
        {},
    )
    group_summary = "; ".join(
        f"{group}: {counts.get('successful_outliers', 0)} successful outlier(s) "
        f"from {counts.get('researched', 0)} researched channel(s)"
        for group, counts in group_diagnostics.items()
    ) or "No configured competitor-group evidence."
    lines = [
        "## RITZZ topic approval required",
        "",
        "Reply to the pipeline approval issue with exactly `1`, `2`, `3`, or `4`.",
        "These numbers are selection labels only; candidates are not ranked.",
        "The selected candidate will be persisted before production continues.",
        "",
        "Discovery: " + "; ".join(discovery_notes),
        "Competitor research: " + group_summary,
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
