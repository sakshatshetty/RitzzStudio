from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from modules.analytics.inventory import InventoryManager


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


class SnapshotPlanner:
    """Determine when 24h, 48h, 7d, 14d, and 28d snapshots should be collected."""

    def __init__(self, published_at: str | None = None):
        self.published_at = published_at

    def snapshot_status_for(self, reference_time: str | None = None) -> dict[str, str]:
        published = _parse_iso(self.published_at)
        reference = _parse_iso(reference_time) if reference_time else datetime.now(timezone.utc)
        if published is None or reference is None:
            return {
                "24h": "pending",
                "48h": "pending",
                "7d": "pending",
                "14d": "pending",
                "28d": "pending",
            }

        elapsed_hours = max(0.0, (reference - published).total_seconds() / 3600.0)
        return {
            "24h": "completed" if elapsed_hours >= 24 else "pending",
            "48h": "completed" if elapsed_hours >= 48 else "pending",
            "7d": "completed" if elapsed_hours >= 168 else "pending",
            "14d": "completed" if elapsed_hours >= 336 else "pending",
            "28d": "completed" if elapsed_hours >= 672 else "pending",
        }


def _normalize_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(metrics)
    for key in ("views", "likes", "comments", "shares", "estimated_minutes_watched", "subscribers_gained", "subscribers_lost"):
        value = normalized.get(key)
        if value is None:
            normalized[key] = 0
        else:
            normalized[key] = float(value)
    return normalized


def build_snapshot(raw_metrics: dict[str, Any]) -> dict[str, Any]:
    """Create a versioned analytics snapshot with raw, normalized, and derived layers."""
    raw = dict(raw_metrics)
    normalized = _normalize_metrics(raw)
    derived = derive_metrics(normalized)
    published_at = raw.get("published_at") or normalized.get("published_at")
    return {
        "raw": raw,
        "normalized": normalized,
        "derived": derived,
        "published_at": published_at,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_status": SnapshotPlanner(published_at=published_at).snapshot_status_for(published_at),
    }


def derive_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    """Create deterministic derived metrics while preserving source metrics."""
    values = _normalize_metrics(metrics)
    views = float(values.get("views") or 0)
    likes = float(values.get("likes") or 0)
    comments = float(values.get("comments") or 0)
    shares = float(values.get("shares") or 0)
    subscribers_gained = float(values.get("subscribers_gained") or 0)
    subscribers_lost = float(values.get("subscribers_lost") or 0)
    estimated_minutes_watched = float(values.get("estimated_minutes_watched") or 0)

    derived = {
        "like_rate": likes / views if views else 0.0,
        "comment_rate": comments / views if views else 0.0,
        "share_rate": shares / views if views else 0.0,
        "subscriber_conversion_rate": subscribers_gained / views if views else 0.0,
        "watch_time_per_view": estimated_minutes_watched / views if views else 0.0,
        "source_metrics": dict(values),
        "calculation_timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return derived


def generate_learning_report(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate snapshot results into a simple learning summary for M7."""
    if not snapshots:
        return {
            "total_videos": 0,
            "avg_like_rate": 0.0,
            "avg_comment_rate": 0.0,
            "avg_share_rate": 0.0,
            "avg_watch_time_per_view": 0.0,
            "videos": [],
        }

    like_rates = [float(item["derived"]["like_rate"]) for item in snapshots if "derived" in item and "like_rate" in item["derived"]]
    comment_rates = [float(item["derived"]["comment_rate"]) for item in snapshots if "derived" in item and "comment_rate" in item["derived"]]
    share_rates = [float(item["derived"]["share_rate"]) for item in snapshots if "derived" in item and "share_rate" in item["derived"]]
    watch_time = [float(item["derived"]["watch_time_per_view"]) for item in snapshots if "derived" in item and "watch_time_per_view" in item["derived"]]

    return {
        "total_videos": len(snapshots),
        "avg_like_rate": sum(like_rates) / len(like_rates) if like_rates else 0.0,
        "avg_comment_rate": sum(comment_rates) / len(comment_rates) if comment_rates else 0.0,
        "avg_share_rate": sum(share_rates) / len(share_rates) if share_rates else 0.0,
        "avg_watch_time_per_view": sum(watch_time) / len(watch_time) if watch_time else 0.0,
        "videos": [
            {
                "published_at": item.get("published_at"),
                "captured_at": item.get("captured_at"),
                "like_rate": item.get("derived", {}).get("like_rate"),
                "comment_rate": item.get("derived", {}).get("comment_rate"),
                "share_rate": item.get("derived", {}).get("share_rate"),
            }
            for item in snapshots
        ],
    }


class YouTubeAnalyticsProvider:
    """Read summary analytics for a published YouTube video using the readonly analytics scope."""

    SCOPES = ["https://www.googleapis.com/auth/yt-analytics.readonly"]

    def __init__(
        self,
        credentials_file: str | Path,
        token_file: str | Path,
        *,
        service: Any | None = None,
        service_builder: Callable[[str | Path, str | Path, list[str]], Any] | None = None,
    ):
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self._service = service
        self._service_builder = service_builder or self._build_service

    @property
    def service(self) -> Any:
        if self._service is None:
            self._service = self._service_builder(
                self.credentials_file,
                self.token_file,
                self.SCOPES,
            )
        return self._service

    def fetch_video_metrics(self, video_id: str, *, start_date: str = "2000-01-01", end_date: str | None = None) -> dict[str, float]:
        if not video_id or not str(video_id).strip():
            raise ValueError("A YouTube video ID is required for analytics collection.")

        if end_date is None:
            end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if not hasattr(self.service, "reports"):
            return {
                "views": 0.0,
                "likes": 0.0,
                "comments": 0.0,
                "shares": 0.0,
                "estimated_minutes_watched": 0.0,
                "subscribers_gained": 0.0,
                "subscribers_lost": 0.0,
            }

        response = self.service.reports().query(
            ids="channel==MINE",
            filters=f"video=={video_id}",
            startDate=start_date,
            endDate=end_date,
            metrics="views,estimatedMinutesWatched,likes,comments,shares,subscribersGained,subscribersLost",
            dimensions="day",
            sort="day",
        ).execute()

        headers = [column.get("name") for column in response.get("columnHeaders", [])]
        row_values = response.get("rows", [])
        totals = {
            "views": 0.0,
            "likes": 0.0,
            "comments": 0.0,
            "shares": 0.0,
            "estimated_minutes_watched": 0.0,
            "subscribers_gained": 0.0,
            "subscribers_lost": 0.0,
        }

        for row in row_values:
            for index, header in enumerate(headers):
                if index >= len(row):
                    continue
                value = row[index]
                if header == "views":
                    totals["views"] += float(value or 0)
                elif header == "likes":
                    totals["likes"] += float(value or 0)
                elif header == "comments":
                    totals["comments"] += float(value or 0)
                elif header == "shares":
                    totals["shares"] += float(value or 0)
                elif header == "estimatedMinutesWatched":
                    totals["estimated_minutes_watched"] += float(value or 0)
                elif header == "subscribersGained":
                    totals["subscribers_gained"] += float(value or 0)
                elif header == "subscribersLost":
                    totals["subscribers_lost"] += float(value or 0)

        return totals

    @staticmethod
    def _build_service(
        credentials_file: str | Path,
        token_file: str | Path,
        scopes: list[str],
    ) -> Any:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "YouTube analytics requires google-api-python-client, google-auth, and google-auth-oauthlib. "
                "Install the project requirements first."
            ) from exc

        token_path = Path(token_file)
        credentials: Any | None = None
        if token_path.exists():
            credentials = Credentials.from_authorized_user_file(str(token_path), scopes)

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), scopes)
                credentials = flow.run_local_server(port=0)
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(credentials.to_json(), encoding="utf-8")

        return build("youtubeAnalytics", "v2", credentials=credentials)


class AnalyticsCollector:
    """Collect and persist published-video analytics for the project inventory and learning loop."""

    def __init__(self, analytics_dir: str | Path, provider: YouTubeAnalyticsProvider | None = None):
        self.analytics_dir = Path(analytics_dir)
        self.analytics_dir.mkdir(parents=True, exist_ok=True)
        self.provider = provider

    def collect_for_project(self, project: Any, project_dir: str | Path, *, inventory_path: str | Path | None = None) -> dict[str, Any]:
        project_dir = Path(project_dir)
        publish_file = project_dir / "publishing" / "publish.json"
        if not publish_file.exists():
            raise FileNotFoundError(f"No publish.json exists for project at {project_dir}")

        publish_data = json.loads(publish_file.read_text(encoding="utf-8"))
        video_id = str(publish_data.get("video_id") or "").strip()
        if not video_id:
            raise ValueError(f"Project {project.project_id} has no YouTube video_id in its publish artifact.")

        provider = self.provider or YouTubeAnalyticsProvider(
            credentials_file=Path("D:/AIStudio/Secrets/google_Auth.json"),
            token_file=Path("D:/AIStudio/Secrets/youtube-token.json"),
        )
        metrics = provider.fetch_video_metrics(video_id)
        snapshot = build_snapshot({
            "project_id": project.project_id,
            "video_id": video_id,
            "published_at": publish_data.get("scheduled_for") or publish_data.get("published_at"),
            **metrics,
        })

        artifact_path = self.analytics_dir / f"{project.project_id}_{video_id}_analytics.json"
        artifact_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

        inventory_file = Path(inventory_path) if inventory_path else project_dir.parent / "inventory.json"
        inventory = InventoryManager(inventory_file)
        record = inventory.load().get("projects", [])
        existing = next((item for item in record if item.get("project_id") == project.project_id), None)
        if existing is None:
            project_record = {
                "project_id": project.project_id,
                "topic": project.title,
                "project_status": "published",
                "youtube": {"video_id": video_id, "url": publish_data.get("url")},
                "analytics": {},
            }
            project_record["analytics"] = {
                "first_collected_at": snapshot["captured_at"],
                "last_collected_at": snapshot["captured_at"],
                "latest_snapshot": snapshot,
            }
            inventory.upsert(project_record)
        else:
            existing["analytics"] = {
                "first_collected_at": existing.get("analytics", {}).get("first_collected_at") or snapshot["captured_at"],
                "last_collected_at": snapshot["captured_at"],
                "latest_snapshot": snapshot,
            }
            inventory.upsert(existing)

        return snapshot
