from __future__ import annotations

import json
from pathlib import Path

from modules.analytics.collector import (
    AnalyticsCollector,
    SnapshotPlanner,
    build_snapshot,
    derive_metrics,
    generate_learning_report,
)
from modules.analytics.inventory import InventoryManager
from modules.project.manager import ProjectManager


def test_inventory_from_project_builds_published_record(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    manager = ProjectManager(projects_dir)
    project = manager.create_project("Why Do Pirates Wear Eye Patches?")
    project_dir = projects_dir / f"{project.project_id}_{project.slug}"
    publish_dir = project_dir / "publishing"
    publish_dir.mkdir(parents=True, exist_ok=True)

    publish_result = {
        "publish_status": "PUBLISHED",
        "video_id": "abc123",
        "url": "https://youtu.be/abc123",
        "title": "Why Do Pirates Wear Eye Patches? The Surprising Medical Reason",
        "scheduled_for": "2026-10-02T12:00:00+00:00",
    }
    (publish_dir / "publish.json").write_text(json.dumps(publish_result), encoding="utf-8")

    inventory = InventoryManager(tmp_path / "inventory.json")
    record = inventory.build_for_project(project, project_dir)

    assert record["project_id"] == project.project_id
    assert record["project_status"] == "published"
    assert record["youtube"]["video_id"] == "abc123"
    assert record["youtube"]["url"] == "https://youtu.be/abc123"
    assert record["analytics"]["last_collected_at"] is None


def test_snapshot_planner_marks_pending_when_video_is_too_new():
    planner = SnapshotPlanner(published_at="2026-10-01T10:00:00+00:00")
    status = planner.snapshot_status_for("2026-10-01T15:00:00+00:00")

    assert status["24h"] == "pending"
    assert status["48h"] == "pending"
    assert status["7d"] == "pending"


def test_derive_metrics_handles_zero_divisors_and_keeps_source_data():
    metrics = {
        "views": 100,
        "likes": 20,
        "comments": 5,
        "shares": 2,
        "estimated_minutes_watched": 300,
        "subscribers_gained": 4,
        "subscribers_lost": 1,
    }

    record = derive_metrics(metrics)

    assert record["like_rate"] == 0.2
    assert record["comment_rate"] == 0.05
    assert record["share_rate"] == 0.02
    assert record["subscriber_conversion_rate"] == 0.04
    assert record["source_metrics"]["views"] == 100


def test_snapshot_planner_marks_completed_windows_when_threshold_is_reached():
    planner = SnapshotPlanner(published_at="2026-10-01T10:00:00+00:00")
    status = planner.snapshot_status_for("2026-10-02T10:00:00+00:00")

    assert status["24h"] == "completed"
    assert status["48h"] == "pending"


def test_build_snapshot_and_learning_report_preserve_raw_normalized_derived_layers():
    raw_metrics = {
        "views": 1000,
        "likes": 200,
        "comments": 25,
        "shares": 15,
        "estimated_minutes_watched": 4500,
        "subscribers_gained": 30,
        "subscribers_lost": 5,
        "published_at": "2026-10-01T10:00:00+00:00",
    }

    snapshot = build_snapshot(raw_metrics)
    report = generate_learning_report([snapshot])

    assert snapshot["raw"]["views"] == 1000
    assert snapshot["normalized"]["views"] == 1000
    assert snapshot["derived"]["like_rate"] == 0.2
    assert report["total_videos"] == 1
    assert report["avg_like_rate"] == 0.2


def test_analytics_collector_persists_snapshot_and_inventory_update(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    manager = ProjectManager(projects_dir)
    project = manager.create_project("Analytics collector test")
    project_dir = projects_dir / f"{project.project_id}_{project.slug}"
    publish_dir = project_dir / "publishing"
    publish_dir.mkdir(parents=True, exist_ok=True)
    (publish_dir / "publish.json").write_text(
        '{"publish_status": "PUBLISHED", "video_id": "abc123", "url": "https://youtu.be/abc123", "scheduled_for": "2026-10-02T12:00:00+00:00"}',
        encoding="utf-8",
    )

    class FakeProvider:
        def fetch_video_metrics(self, video_id: str):
            assert video_id == "abc123"
            return {
                "views": 1000,
                "likes": 200,
                "comments": 25,
                "shares": 15,
                "estimated_minutes_watched": 4500,
                "subscribers_gained": 30,
                "subscribers_lost": 5,
            }

    collector = AnalyticsCollector(tmp_path / "analytics", provider=FakeProvider())
    snapshot = collector.collect_for_project(project, project_dir, inventory_path=tmp_path / "inventory.json")

    assert snapshot["raw"]["video_id"] == "abc123"
    assert snapshot["derived"]["like_rate"] == 0.2

    inventory = InventoryManager(tmp_path / "inventory.json").load()
    project_record = next(item for item in inventory["projects"] if item["project_id"] == project.project_id)
    assert project_record["youtube"]["video_id"] == "abc123"
    assert project_record["analytics"]["latest_snapshot"]["raw"]["views"] == 1000
