from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modules.project.models import Project


DEFAULT_INVENTORY = {
    "projects": [],
    "published_videos": [],
    "last_updated": None,
}


class InventoryManager:
    """Track published project records and their YouTube metadata."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return json.loads(json.dumps(DEFAULT_INVENTORY))
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return json.loads(json.dumps(DEFAULT_INVENTORY))
        merged = json.loads(json.dumps(DEFAULT_INVENTORY))
        merged.update(data)
        return merged

    def save(self, inventory: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")

    def build_for_project(self, project: Project, project_dir: str | Path) -> dict[str, Any]:
        project_dir = Path(project_dir)
        publish_file = project_dir / "publishing" / "publish.json"
        publish_data: dict[str, Any] = {}
        if publish_file.exists():
            publish_data = json.loads(publish_file.read_text(encoding="utf-8"))

        project_status = (publish_data.get("publish_status") or "published").lower()
        project_status = "published" if project_status in {"published", "private", "complete"} else project_status

        record = {
            "project_id": project.project_id,
            "topic": project.title,
            "project_status": project_status,
            "youtube": {
                "video_id": publish_data.get("video_id"),
                "url": publish_data.get("url"),
                "published_at": publish_data.get("scheduled_for") or publish_data.get("published_at"),
                "visibility": "private" if project_status == "private" else "public",
            },
            "content": {
                "title": publish_data.get("title") or project.title,
                "duration_seconds": 0,
                "topic_category": "mixed_curiosity",
                "topic_type": "curiosity",
            },
            "packaging": {
                "title_angle": "pending",
                "thumbnail_concept": "pending",
                "thumbnail_variant": "A",
            },
            "analytics": {
                "first_collected_at": None,
                "last_collected_at": None,
                "latest_snapshot": None,
            },
        }

        self.upsert(record)
        return record

    def upsert(self, record: dict[str, Any]) -> dict[str, Any]:
        inventory = self.load()
        projects = inventory.setdefault("projects", [])
        existing = next((item for item in projects if item.get("project_id") == record.get("project_id")), None)
        if existing is None:
            projects.append(record)
        else:
            projects[projects.index(existing)] = record

        published_videos = [item for item in projects if item.get("project_status") in {"published", "private"} and item.get("youtube", {}).get("video_id")]
        inventory["published_videos"] = published_videos
        inventory["last_updated"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        self.save(inventory)
        return record

    def validate_record(self, record: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        if not record.get("project_id"):
            errors.append("missing project_id")
        if not record.get("topic"):
            errors.append("missing topic")
        youtube = record.get("youtube", {})
        if not youtube.get("video_id"):
            errors.append("missing YouTube video_id")
        if not youtube.get("url"):
            errors.append("missing YouTube URL")
        if not record.get("content", {}).get("title"):
            errors.append("missing content title")
        return {
            "valid": not errors,
            "errors": errors,
            "status": "complete" if not errors else "incomplete",
        }

    def generate_inventory_report(self) -> dict[str, Any]:
        inventory = self.load()
        projects = inventory.get("projects", [])
        published = [item for item in projects if item.get("project_status") in {"published", "private"}]
        missing_ids = [item for item in published if not item.get("youtube", {}).get("video_id")]
        missing_urls = [item for item in published if not item.get("youtube", {}).get("url")]
        incomplete = [item for item in projects if not self.validate_record(item)["valid"]]
        return {
            "total_projects": len(projects),
            "total_published_videos": len(published),
            "missing_youtube_ids": len(missing_ids),
            "missing_urls": len(missing_urls),
            "incomplete_records": len(incomplete),
            "analytics_enabled_videos": 0,
            "errors": [
                f"{item.get('project_id')}: {error}"
                for item in incomplete
                for error in self.validate_record(item)["errors"]
            ],
        }
