import json

from modules.topic_intelligence.learning import (
    load_m7_learning_signals,
    sample_size_level,
    signals_for_topic,
)


def _record(project_id: str, topic: str, views: int) -> dict:
    return {
        "project_id": project_id,
        "topic": topic,
        "project_status": "published",
        "youtube": {"video_id": f"video-{project_id}"},
        "analytics": {
            "latest_snapshot": {
                "captured_at": "2026-09-01T00:00:00+00:00",
                "normalized": {"views": views},
                "derived": {"like_rate": 0.1, "watch_time_per_view": 2.5},
            }
        },
    }


def test_sample_size_levels_are_explicit_and_one_video_is_insufficient():
    assert sample_size_level(0) == "INSUFFICIENT"
    assert sample_size_level(1) == "INSUFFICIENT"
    assert sample_size_level(3) == "LIMITED"
    assert sample_size_level(6) == "EMERGING"
    assert sample_size_level(12) == "ESTABLISHED"
    assert sample_size_level(
        2,
        limited_threshold=2,
        emerging_threshold=4,
        established_threshold=8,
    ) == "LIMITED"


def test_missing_m7_inventory_is_unavailable_without_failing(tmp_path):
    signals, videos = load_m7_learning_signals(tmp_path / "missing.json")
    assert signals.status == "UNAVAILABLE"
    assert signals.sample_size == "INSUFFICIENT"
    assert signals.data_quality == "MISSING_INVENTORY"
    assert videos == []


def test_existing_m7_inventory_is_read_only_and_attaches_topic_evidence(tmp_path):
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps({
        "projects": [
            _record("1", "Why do pirates wear eye patches?", 1200),
            _record("2", "Why do sailors use eye patches?", 800),
        ],
        "published_videos": [_record("1", "duplicate entry", 1200)],
    }))
    before = inventory_path.read_text()

    signals, videos = load_m7_learning_signals(inventory_path)
    attached = signals_for_topic("Why do pirates wear eye patches?", signals, videos)

    assert signals.status == "AVAILABLE"
    assert signals.historical_video_count == 2
    assert signals.sample_size == "INSUFFICIENT"
    assert len(attached["topic_signals"]) == 2
    assert attached["topic_signals"][0]["metrics"]["views"] == 1200
    assert inventory_path.read_text() == before


def test_no_snapshot_data_is_not_converted_to_performance_zeros(tmp_path):
    inventory_path = tmp_path / "inventory.json"
    inventory_path.write_text(json.dumps({"projects": [{"project_id": "1", "topic": "A topic"}]}))

    signals, videos = load_m7_learning_signals(inventory_path)

    assert signals.historical_video_count == 0
    assert signals.data_quality == "NO_HISTORY"
    assert videos == []
