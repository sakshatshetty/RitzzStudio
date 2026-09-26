from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from modules.project.manager import ProjectManager
from modules.project.models import Project


@dataclass
class PublishApproval:
    approved: bool = False
    approved_by: str = ""
    approved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PublishApproval":
        return cls(
            approved=bool(data.get("approved", False)),
            approved_by=str(data.get("approved_by", "")),
            approved_at=data.get("approved_at"),
        )


@dataclass
class PublishResult:
    publish_status: str
    video_id: str
    url: str
    title: str
    scheduled_for: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "publish_status": self.publish_status,
            "video_id": self.video_id,
            "url": self.url,
            "title": self.title,
            "scheduled_for": self.scheduled_for,
        }


class FakeYouTubeProvider:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def upload_video(
        self,
        *,
        video_file: str | Path,
        title: str,
        description: str,
        metadata: dict[str, Any],
        scheduled_for: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append({
            "video_file": str(video_file),
            "title": title,
            "description": description,
            "metadata": metadata,
        })
        return {
            "video_id": f"yt_{abs(hash((title, str(video_file)))) % 1000000:06d}",
            "url": f"https://youtu.be/{abs(hash((title, str(video_file)))) % 1000000:06d}",
        }


class PublishingProvider(Protocol):
    def upload_video(
        self,
        *,
        video_file: str | Path,
        title: str,
        description: str,
        metadata: dict[str, Any],
        scheduled_for: str | None = None,
    ) -> dict[str, Any]: ...


class PublishingEngine:
    """Handles upload and scheduling only after explicit approval."""

    def __init__(self, projects_dir: str | Path, provider: PublishingProvider | None = None):
        self.projects_dir = Path(projects_dir)
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        self.provider = provider or FakeYouTubeProvider()

    def create_approval(self, project: Project, *, approved: bool, approved_by: str) -> PublishApproval:
        if approved and not approved_by.strip():
            raise ValueError("An approving user is required for an approved publish artifact.")
        project_path = self.projects_dir / f"{project.project_id}_{project.slug}"
        project_path.mkdir(parents=True, exist_ok=True)
        approval = PublishApproval(
            approved=approved,
            approved_by=approved_by.strip(),
            approved_at=datetime.now(timezone.utc).isoformat(),
        )
        (project_path / "publishing").mkdir(exist_ok=True)
        (project_path / "publishing" / "approval.json").write_text(
            json.dumps(approval.to_dict(), indent=2),
            encoding="utf-8",
        )
        return approval

    def _load_approval(self, project: Project) -> PublishApproval:
        project_path = self.projects_dir / f"{project.project_id}_{project.slug}"
        approval_file = project_path / "publishing" / "approval.json"
        if not approval_file.exists():
            raise ValueError("No publish approval exists for this project.")
        return PublishApproval.from_dict(json.loads(approval_file.read_text(encoding="utf-8")))

    def publish_video(
        self,
        *,
        project: Project,
        video_file: str | Path,
        title: str,
        description: str,
        metadata: dict[str, Any],
        scheduled_for: str | None = None,
    ) -> PublishResult:
        approval = self._load_approval(project)
        if not approval.approved:
            raise ValueError("Uploads require explicit human approval before publishing.")

        schedule = scheduled_for or self.load_publish_schedule(project)
        if not schedule:
            raise ValueError("Uploads require a publish schedule before publishing.")

        response = self.provider.upload_video(
            video_file=video_file,
            title=title,
            description=description,
            metadata=metadata,
            scheduled_for=schedule,
        )

        project_path = self.projects_dir / f"{project.project_id}_{project.slug}"
        publish_dir = project_path / "publishing"
        publish_dir.mkdir(parents=True, exist_ok=True)

        result = PublishResult(
            publish_status="PUBLISHED",
            video_id=response["video_id"],
            url=response["url"],
            title=title,
            scheduled_for=schedule,
        )
        (publish_dir / "publish.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        return result

    def publish_project(
        self,
        *,
        project: Project,
        video_file: str | Path,
        title: str,
        description: str,
        metadata: dict[str, Any],
        approved_by: str,
        scheduled_for: str,
    ) -> PublishResult:
        approval = self._load_approval(project)
        if not approval.approved:
            raise ValueError("Uploads require explicit human approval before publishing.")
        if approval.approved_by != approved_by.strip():
            raise ValueError("The supplied approver does not match the saved publish approval.")
        self.set_publish_schedule(project, scheduled_for)
        return self.publish_video(
            project=project,
            video_file=video_file,
            title=title,
            description=description,
            metadata=metadata,
            scheduled_for=scheduled_for,
        )

    def set_publish_schedule(self, project: Project, scheduled_for: str) -> str:
        project_path = self.projects_dir / f"{project.project_id}_{project.slug}"
        publish_dir = project_path / "publishing"
        publish_dir.mkdir(parents=True, exist_ok=True)

        if not scheduled_for or not scheduled_for.strip():
            raise ValueError("A publish schedule value is required.")

        schedule_file = publish_dir / "schedule.json"
        schedule_file.write_text(json.dumps({"scheduled_for": scheduled_for.strip()}, indent=2), encoding="utf-8")
        return scheduled_for.strip()

    def load_publish_schedule(self, project: Project) -> str | None:
        project_path = self.projects_dir / f"{project.project_id}_{project.slug}"
        schedule_file = project_path / "publishing" / "schedule.json"
        if not schedule_file.exists():
            return None
        payload = json.loads(schedule_file.read_text(encoding="utf-8"))
        return payload.get("scheduled_for")

    @staticmethod
    def load_publish_result(project_path: str | Path) -> PublishResult:
        path = Path(project_path) / "publishing" / "publish.json"
        if not path.exists():
            raise FileNotFoundError(f"No publish result exists at {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return PublishResult(
            publish_status=payload["publish_status"],
            video_id=payload["video_id"],
            url=payload["url"],
            title=payload["title"],
            scheduled_for=payload.get("scheduled_for"),
        )
