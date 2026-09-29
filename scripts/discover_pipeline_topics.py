"""Discover four pipeline candidates without interactive terminal input."""

import json
import os
from pathlib import Path

from modules.topic_intelligence.engine import TopicIntelligenceEngine
from modules.topic_intelligence.inventory import ContentInventoryManager
from modules.topic_intelligence.models import TopicDiscoveryRequest


def _candidate_markdown(index: int, candidate) -> str:
    score = (
        f"{candidate.opportunity_score:.1f}/100"
        if candidate.opportunity_score is not None
        else "unscored"
    )
    rationale = "; ".join(candidate.rationale[:2]) or "No additional rationale recorded."
    return (
        f"### {index}. {candidate.topic}\n"
        f"- Candidate ID: `{candidate.candidate_id}`\n"
        f"- Type: `{candidate.opportunity_type}`\n"
        f"- Opportunity score: `{score}`\n"
        f"- Validation: `{candidate.validation_status}`\n"
        f"- Why it is interesting: {candidate.why_interesting or 'Not provided.'}\n"
        f"- Notes: {rationale}\n"
    )


def main() -> int:
    output_directory = Path(os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts"))
    output_directory.mkdir(parents=True, exist_ok=True)

    mode = os.environ.get("RITZZ_DISCOVERY_MODE", "TRENDING").upper()
    timeframe = os.environ.get("RITZZ_DISCOVERY_TIMEFRAME", "this week")
    trend_topic = os.environ.get("RITZZ_TREND_TOPIC") or None
    inventory_file = Path(
        os.environ.get("RITZZ_INVENTORY_FILE", "data/content_inventory.json")
    )
    report = TopicIntelligenceEngine(
        inventory_manager=ContentInventoryManager(inventory_file),
    ).discover(
        TopicDiscoveryRequest(
            mode=mode,
            timeframe=timeframe,
            trend_topic=trend_topic,
            force_refresh=True,
        )
    )
    candidates = report.candidates[:4]
    if len(candidates) != 4:
        raise RuntimeError(f"Expected exactly four topic candidates, received {len(candidates)}.")

    payload = {
        "report_id": report.report_id,
        "created_at": report.created_at,
        "provider": report.provider,
        "request": report.request.model_dump(mode="json"),
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
