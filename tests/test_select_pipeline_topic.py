import json

from scripts.select_pipeline_topic import main


def test_numbered_selection_persists_candidate_provenance(tmp_path, monkeypatch):
    artifact_directory = tmp_path / ".pipeline-artifacts"
    artifact_directory.mkdir()
    (artifact_directory / "topic_candidates.json").write_text(json.dumps({
        "report_id": "report-1",
        "candidates": [{
            "candidate_id": "candidate-1",
            "topic": "Why do cats purr?",
            "angle": "Explain the biological purpose of purring.",
            "provider": "vidiq_mcp",
            "discovery_sources": ["trending", "rising"],
            "raw_evidence": {"source_id": "provider-record-1"},
            "current_vidiq_demand_signals": {
                "search_volume": {
                    "value": 1200,
                    "unit": "searches",
                    "available": True,
                    "source": "vidIQ",
                }
            },
            "competition_saturation_signal": {
                "value": 45,
                "unit": "score",
                "available": True,
                "source": "vidIQ",
            },
            "competitor_evidence": [{"topic": "cat purring", "source": "vidIQ MCP"}],
            "ritzz_fit": {"fit_status": "PASS", "fit_score": 82},
            "ritzz_learning_signals": {"sample_size": "INSUFFICIENT"},
            "discovered_at": "2026-09-30T00:00:00+00:00",
        }],
    }))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RITZZ_SELECTED_TOPIC_NUMBER", "1")
    monkeypatch.setenv("RITZZ_TARGET_DURATION_MINUTES", "8")
    monkeypatch.setenv("RITZZ_MINIMUM_DURATION_MINUTES", "8")

    assert main() == 0

    selection = json.loads(
        (artifact_directory / "topic_selection.json").read_text()
    )
    assert selection["normalized_topic"] == "why do cats purr"
    assert selection["angle"] == "Explain the biological purpose of purring."
    assert selection["source_evidence"]["discovery_sources"] == ["trending", "rising"]
    assert selection["trend_evidence"]["search_volume"]["value"] == 1200
    assert selection["competitor_evidence"][0]["topic"] == "cat purring"
    assert selection["ritzz_fit"]["fit_status"] == "PASS"
    assert selection["ritzz_learning_signals"]["sample_size"] == "INSUFFICIENT"
    assert selection["approval_metadata"]["selection_number"] == 1
