"""Persist the numbered topic choice from a GitHub Actions run."""

import json
import os
from pathlib import Path

from modules.topic_intelligence.models import TopicSelection


def main() -> int:
    candidates_path = Path(
        os.environ.get("RITZZ_CANDIDATES_FILE", ".pipeline-artifacts/topic_candidates.json")
    )
    output_directory = Path(os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts"))
    selection_number = int(os.environ["RITZZ_SELECTED_TOPIC_NUMBER"])

    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", [])
    if not 1 <= selection_number <= len(candidates):
        raise ValueError(f"Topic selection must be between 1 and {len(candidates)}.")

    candidate = candidates[selection_number - 1]
    selection = TopicSelection(
        report_id=payload.get("report_id"),
        candidate_id=candidate["candidate_id"],
        topic=candidate["topic"],
        source="discovery",
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    selection_path = output_directory / "topic_selection.json"
    selection_path.write_text(selection.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(f"Selected topic {selection_number}: {selection.topic}")
    print(f"Persisted selection: {selection_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
