"""Persist the numbered topic choice from a GitHub Actions run."""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.topic_intelligence.models import TopicSelection
from modules.topic_intelligence.inventory import normalize_topic


def main() -> int:
    candidates_path = Path(
        os.environ.get("RITZZ_CANDIDATES_FILE", ".pipeline-artifacts/topic_candidates.json")
    )
    output_directory = Path(os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts"))
    selection_number = int(os.environ["RITZZ_SELECTED_TOPIC_NUMBER"])
    target_minutes = float(os.environ.get("RITZZ_TARGET_DURATION_MINUTES", "8"))
    minimum_minutes = float(os.environ.get("RITZZ_MINIMUM_DURATION_MINUTES", "8"))
    if target_minutes <= 0 or minimum_minutes <= 0:
        raise ValueError("Video durations must be greater than zero minutes.")
    if minimum_minutes > target_minutes:
        raise ValueError("Minimum duration cannot exceed target duration.")

    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", [])
    if not 1 <= selection_number <= len(candidates):
        raise ValueError(f"Topic selection must be between 1 and {len(candidates)}.")

    candidate = candidates[selection_number - 1]
    demand_signals = candidate.get("current_vidiq_demand_signals")
    if not isinstance(demand_signals, dict):
        demand_signals = candidate.get("evidence", {})
    selection = TopicSelection(
        report_id=payload.get("report_id"),
        candidate_id=candidate["candidate_id"],
        topic=candidate["topic"],
        source="discovery",
        target_duration_seconds=round(target_minutes * 60),
        minimum_duration_seconds=round(minimum_minutes * 60),
        normalized_topic=normalize_topic(candidate["topic"]),
        angle=candidate.get("angle"),
        source_evidence={
            "discovery_sources": candidate.get("discovery_sources", []),
            "raw_evidence": candidate.get("raw_evidence", {}),
            "provider": candidate.get("provider"),
            "vidiq_status": candidate.get("vidiq_status", "UNAVAILABLE"),
        },
        trend_evidence=demand_signals,
        competitor_evidence=candidate.get("competitor_evidence", []),
        ritzz_fit=candidate.get("ritzz_fit"),
        ritzz_learning_signals=candidate.get("ritzz_learning_signals"),
        approval_metadata={"selection_number": selection_number},
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    selection_path = output_directory / "topic_selection.json"
    selection_path.write_text(selection.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"Selected topic {selection_number}: {selection.topic}")
    print(f"Persisted selection: {selection_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
