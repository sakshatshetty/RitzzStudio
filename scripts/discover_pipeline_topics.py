"""Generate and score a small human-approved topic shortlist."""

import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.topic_intelligence.inventory import ContentInventoryManager
from modules.topic_intelligence.models import (
    OpportunityCandidate,
    OpportunityReport,
    TopicDiscoveryRequest,
)
from modules.topic_intelligence.pipeline_topic_discovery import (
    DISCOVERY_MODE,
    FINAL_CANDIDATE_LIMIT,
    FINAL_CANDIDATE_MINIMUM,
    PIPELINE_TOPIC_SOURCE,
    TOPIC_OPPORTUNITY_COUNT,
    VIDIQ_USAGE_MODE,
    GPTKeywordTopicDiscovery,
    TopicDiscoveryFailure,
    format_metric_value,
)
from modules.topic_intelligence.providers.vidiq_mcp import VidiqMcpProvider


def _metric_text(candidate: OpportunityCandidate, key: str) -> str:
    metric = candidate.evidence.get(key)
    if metric is None or not metric.available or metric.value is None:
        return "UNAVAILABLE"
    suffix = f" {metric.unit}" if metric.unit else ""
    return f"{format_metric_value(metric.value)}{suffix}"


def _candidate_markdown(index: int, candidate: OpportunityCandidate) -> str:
    fit = candidate.ritzz_fit
    fit_reason = fit.reason if fit else "Not assessed."
    opportunity = candidate.raw_evidence.get("vidiq_opportunity", {})
    idea = candidate.raw_evidence.get("gpt_generated_idea", {})
    return (
        f"### {index}. {candidate.proposed_title or candidate.topic}\n"
        f"- vidIQ opportunity: `{opportunity.get('topic', 'UNAVAILABLE')}`\n"
        f"- vidIQ status: `{candidate.vidiq_status}`\n"
        f"- vidIQ Keyword Score: `{_metric_text(candidate, 'keyword_score')}`\n"
        f"- vidIQ Volume Score: `{_metric_text(candidate, 'volume_score')}`\n"
        f"- Search Volume: `{_metric_text(candidate, 'search_volume')}`\n"
        f"- Competition: `{_metric_text(candidate, 'competition')}`\n"
        f"- Growth / trend: `{_metric_text(candidate, 'growth')}`\n"
        f"- Why it fits RITZZ: {fit_reason}\n"
        f"- Curiosity hook: {candidate.why_interesting or 'Not provided.'}\n"
        f"- Explainer angle: {candidate.angle or 'Not provided.'}\n"
        f"- Static visual explanation: "
        f"{idea.get('static_visual_explanation', 'Not provided.')}\n"
        f"- Long-form depth: {idea.get('long_form_depth', 'Not provided.')}\n"
        f"- Originality: {candidate.originality_reason or 'Not provided.'}\n"
        f"- RITZZ inventory: `{candidate.inventory_status}`\n"
    )


def _artifact_payload(report: OpportunityReport) -> dict[str, Any]:
    diagnostics = report.discovery_diagnostics
    return {
        "report_id": report.report_id,
        "created_at": report.created_at,
        "request": report.request.model_dump(mode="json"),
        "provider": report.provider,
        "source": PIPELINE_TOPIC_SOURCE,
        "discovery_mode": DISCOVERY_MODE,
        "vidiq_usage_mode": VIDIQ_USAGE_MODE,
        "diagnostics": diagnostics,
        "rejected_ideas": diagnostics.get("ideas_rejected", []),
        "warnings": report.warnings,
        "candidates": [
            {
                "candidate_number": index,
                **candidate.model_dump(mode="json"),
            }
            for index, candidate in enumerate(report.candidates, start=1)
        ],
    }


def _write_artifacts(
    output_directory: Path,
    report: OpportunityReport | None,
    diagnostics: dict[str, Any],
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    if report is None:
        payload = {
            "provider": PIPELINE_TOPIC_SOURCE,
            "source": PIPELINE_TOPIC_SOURCE,
            "discovery_mode": diagnostics.get("discovery_mode", DISCOVERY_MODE),
            "vidiq_usage_mode": diagnostics.get("vidiq_usage_mode", VIDIQ_USAGE_MODE),
            "diagnostics": diagnostics,
            "rejected_ideas": diagnostics.get("ideas_rejected", []),
            "candidates": [],
        }
        markdown = [
            "# RITZZ topic discovery",
            "",
            f"- Status: `{diagnostics.get('status', 'PROVIDER_ERROR')}`",
            f"- Error: {diagnostics.get('provider_error', 'Topic generation failed.')}",
            "",
            "No candidates were generated.",
            "",
        ]
        rejected_ideas = diagnostics.get("ideas_rejected", [])
        if rejected_ideas:
            markdown.extend(["## Rejected GPT ideas", ""])
            markdown.extend(
                f"- **{idea.get('title', 'Untitled idea')}** — {idea.get('reason', 'No rejection reason recorded.')}"
                for idea in rejected_ideas
            )
            markdown.append("")
    else:
        payload = _artifact_payload(report)
        diagnostics = report.discovery_diagnostics
        markdown = [
            "# RITZZ topic approval required",
            "",
            f"- Status: `{diagnostics.get('status', 'UNKNOWN')}`",
            f"- Source: `{PIPELINE_TOPIC_SOURCE}`",
            f"- Discovery mode: `{diagnostics.get('discovery_mode', DISCOVERY_MODE)}`",
            f"- vidIQ usage mode: `{diagnostics.get('vidiq_usage_mode', VIDIQ_USAGE_MODE)}`",
            f"- vidIQ discovery operations: `{diagnostics.get('vidiq_discovery_operation_count', 0)}`",
            f"- vidIQ opportunities returned: `{diagnostics.get('vidiq_opportunities_returned', 0)}`",
            f"- GPT calls: `{diagnostics.get('gpt_calls_made', 0)}`",
            f"- GPT ideas generated: `{diagnostics.get('gpt_ideas_generated', 0)}`",
            f"- GPT ideas rejected: `{diagnostics.get('ideas_rejected_count', 0)}`",
            f"- Candidates shown: `{len(report.candidates)}`",
            "",
            (
                "Choose one candidate by replying with its number. Candidates "
                "are ranked by available vidIQ market signals, but this is not "
                "an automatic selection."
            ),
            "",
        ]
        markdown.extend(
            _candidate_markdown(index, candidate)
            for index, candidate in enumerate(report.candidates, start=1)
        )
        if report.warnings:
            markdown.extend(["## Warnings", ""])
            markdown.extend(f"- {warning}" for warning in report.warnings)
            markdown.append("")
        rejected_ideas = diagnostics.get("ideas_rejected", [])
        if rejected_ideas:
            markdown.extend(["## Rejected GPT ideas", ""])
            markdown.extend(
                f"- **{idea.get('title', 'Untitled idea')}** — {idea.get('reason', 'No rejection reason recorded.')}"
                for idea in rejected_ideas
            )
            markdown.append("")

    (output_directory / "topic_candidates.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_directory / "topic_candidates.md").write_text(
        "\n".join(markdown),
        encoding="utf-8",
    )
    (output_directory / "topic_discovery_diagnostics.json").write_text(
        json.dumps(diagnostics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    output_directory = Path(os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts"))
    inventory_file = Path(
        os.environ.get("RITZZ_INVENTORY_FILE", "data/content_inventory.json")
    )
    discovery = GPTKeywordTopicDiscovery(
        VidiqMcpProvider(),
        ContentInventoryManager(inventory_file),
    )
    try:
        report = discovery.discover(
            TopicDiscoveryRequest(
                niche="RITZZ mixed curiosity explainers",
                limit=TOPIC_OPPORTUNITY_COUNT,
                force_refresh=True,
                pipeline_topic_gate=True,
            )
        )
    except TopicDiscoveryFailure as exc:
        _write_artifacts(output_directory, None, exc.diagnostics)
        status = str(exc.diagnostics.get("status", "TOPIC_DISCOVERY_ERROR"))
        message = (
            "## Topic discovery failed\n\n"
            f"`{status}`: {exc.diagnostics.get('provider_error', str(exc))}\n"
        )
        _write_summary(message)
        print(message, file=sys.stderr)
        return 1

    _write_artifacts(output_directory, report, report.discovery_diagnostics)
    diagnostics = report.discovery_diagnostics
    if diagnostics["status"] != "SUCCESS":
        message = (
            "## Topic discovery produced too few qualified candidates\n\n"
            f"Status: `{diagnostics['status']}`. "
            f"Qualified candidates: {len(report.candidates)} "
            f"(minimum {FINAL_CANDIDATE_MINIMUM}, maximum {FINAL_CANDIDATE_LIMIT}). "
            f"vidIQ returned {diagnostics['vidiq_opportunities_returned']} opportunities; "
            f"GPT generated {diagnostics['gpt_ideas_generated']} ideas and "
            f"{diagnostics['ideas_rejected_count']} were rejected.\n"
        )
        _write_summary(message)
        print(message, file=sys.stderr)
        return 1

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as stream:
            stream.write(f"candidate_count={len(report.candidates)}\n")
    summary = (output_directory / "topic_candidates.md").read_text(encoding="utf-8")
    _write_summary(summary)
    print(summary)
    return 0


def _write_summary(message: str) -> None:
    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_summary:
        with Path(github_summary).open("a", encoding="utf-8") as stream:
            stream.write(message)


if __name__ == "__main__":
    raise SystemExit(main())
