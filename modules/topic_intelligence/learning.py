"""Read-only adapter from the existing M7 analytics inventory to topic discovery."""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from config.settings import (
    RITZZ_M7_EMERGING_THRESHOLD,
    RITZZ_M7_ESTABLISHED_THRESHOLD,
    RITZZ_M7_LIMITED_THRESHOLD,
)


class RitzzLearningSignals(BaseModel):
    status: str = "AVAILABLE"
    historical_video_count: int = 0
    sample_size: str = "INSUFFICIENT"
    confidence: str = "INSUFFICIENT"
    data_quality: str = "NO_HISTORY"
    topic_signals: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def sample_size_level(
    count: int,
    *,
    limited_threshold: int = RITZZ_M7_LIMITED_THRESHOLD,
    emerging_threshold: int = RITZZ_M7_EMERGING_THRESHOLD,
    established_threshold: int = RITZZ_M7_ESTABLISHED_THRESHOLD,
) -> str:
    if count < limited_threshold:
        return "INSUFFICIENT"
    if count < emerging_threshold:
        return "LIMITED"
    if count < established_threshold:
        return "EMERGING"
    return "ESTABLISHED"


def load_m7_learning_signals(path: str | Path) -> tuple[RitzzLearningSignals, list[dict[str, Any]]]:
    """Load existing M7 inventory snapshots without creating or mutating a store."""
    inventory_path = Path(path)
    if not inventory_path.exists():
        return (
            RitzzLearningSignals(
                status="UNAVAILABLE",
                data_quality="MISSING_INVENTORY",
                warnings=[f"M7 inventory was not found at {inventory_path}."],
            ),
            [],
        )
    try:
        payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return (
            RitzzLearningSignals(
                status="UNAVAILABLE",
                data_quality="INVALID_INVENTORY",
                warnings=[f"M7 inventory could not be read: {exc}"],
            ),
            [],
        )
    if not isinstance(payload, dict):
        return (
            RitzzLearningSignals(
                status="UNAVAILABLE",
                data_quality="INVALID_INVENTORY",
                warnings=["M7 inventory must contain a JSON object."],
            ),
            [],
        )

    records = payload.get("projects")
    if not isinstance(records, list):
        records = payload.get("published_videos", [])
    unique: dict[str, dict[str, Any]] = {}
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        analytics = record.get("analytics")
        snapshot = analytics.get("latest_snapshot") if isinstance(analytics, dict) else None
        if not isinstance(snapshot, dict):
            continue
        key = str(record.get("project_id") or record.get("youtube", {}).get("video_id") or record.get("topic") or "")
        if key:
            unique[key] = record

    videos = list(unique.values())
    count = len(videos)
    quality = "NO_HISTORY" if count == 0 else "PARTIAL" if any(
        not _snapshot_metrics(item) for item in videos
    ) else "USABLE"
    signals = RitzzLearningSignals(
        historical_video_count=count,
        sample_size=sample_size_level(count),
        confidence=sample_size_level(count),
        data_quality=quality,
        observations=[
            f"Observed analytics from {count} historical RITZZ video(s); this is descriptive, not predictive."
        ] if count else ["No historical analytics snapshots are available yet."],
    )
    return signals, videos


def signals_for_topic(
    topic: str,
    learning_signals: RitzzLearningSignals,
    videos: list[dict[str, Any]],
) -> dict[str, Any]:
    """Attach lexical topic matches and observed snapshot metrics only."""
    topic_terms = set(_tokens(topic))
    matches = []
    for record in videos:
        prior_topic = str(record.get("topic") or record.get("content", {}).get("title") or "")
        prior_terms = set(_tokens(prior_topic))
        if not topic_terms or not prior_terms:
            continue
        overlap = topic_terms & prior_terms
        if len(overlap) < min(2, len(topic_terms)) or len(overlap) / len(topic_terms) < 0.5:
            continue
        snapshot = record.get("analytics", {}).get("latest_snapshot", {})
        matches.append({
            "topic": prior_topic,
            "project_id": record.get("project_id"),
            "video_id": record.get("youtube", {}).get("video_id"),
            "metrics": _snapshot_metrics(record),
            "source": "M7 analytics inventory",
            "captured_at": snapshot.get("captured_at"),
        })
    return {
        "status": learning_signals.status,
        "historical_video_count": learning_signals.historical_video_count,
        "sample_size": learning_signals.sample_size,
        "confidence": learning_signals.confidence,
        "data_quality": learning_signals.data_quality,
        "topic_signals": matches,
        "observations": learning_signals.observations,
        "warnings": learning_signals.warnings,
    }


def _snapshot_metrics(record: dict[str, Any]) -> dict[str, Any]:
    snapshot = record.get("analytics", {}).get("latest_snapshot", {})
    derived = snapshot.get("derived", {}) if isinstance(snapshot, dict) else {}
    normalized = snapshot.get("normalized", {}) if isinstance(snapshot, dict) else {}
    return {
        key: value
        for key, value in {
            "views": normalized.get("views"),
            "like_rate": derived.get("like_rate"),
            "comment_rate": derived.get("comment_rate"),
            "share_rate": derived.get("share_rate"),
            "watch_time_per_view": derived.get("watch_time_per_view"),
        }.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def _tokens(value: str) -> list[str]:
    ignored = {"a", "an", "and", "are", "do", "does", "for", "how", "in", "is", "it", "of", "the", "to", "what", "why"}
    return [item for item in re.findall(r"[a-z0-9]+", value.casefold()) if item not in ignored]
