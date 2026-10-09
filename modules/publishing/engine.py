from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from modules.project.models import Project
from modules.project.packaging import PackagingArtifact
from modules.publishing.youtube_provider import YouTubeUploadRejected


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
    uploaded_at: str | None = None
    upload_status: str = "UPLOAD_COMPLETE"
    upload_details: dict[str, Any] | None = None
    youtube_processing_status: str = "YOUTUBE_PROCESSING_UNVERIFIED"
    youtube_processing_error: str | None = None
    youtube_details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "publish_status": self.publish_status,
            "video_id": self.video_id,
            "url": self.url,
            "title": self.title,
            "scheduled_for": self.scheduled_for,
            "uploaded_at": self.uploaded_at,
            "upload_status": self.upload_status,
            "upload_details": self.upload_details,
            "youtube_processing_status": self.youtube_processing_status,
            "youtube_processing_error": self.youtube_processing_error,
            "youtube_details": self.youtube_details,
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
        upload_details: dict[str, Any] | None = None,
    ) -> PublishResult:
        approval = self._load_approval(project)
        if not approval.approved:
            raise ValueError("Uploads require explicit human approval before publishing.")

        schedule = scheduled_for or self.load_publish_schedule(project)
        private_only = not schedule and metadata.get("privacy_status") == "private"
        if not schedule and not private_only:
            raise ValueError("Uploads require a publish schedule before publishing.")

        project_path = self.projects_dir / f"{project.project_id}_{project.slug}"
        publish_dir = project_path / "publishing"
        publish_dir.mkdir(parents=True, exist_ok=True)
        result_path = publish_dir / "publish.json"
        attempt_path = publish_dir / "publish_attempt.json"
        changed_master = False
        if result_path.exists():
            previous_result = json.loads(
                result_path.read_text(encoding="utf-8")
            )
            previous_hash = (
                (previous_result.get("upload_details") or {}).get("sha256")
                if isinstance(previous_result, dict)
                else None
            )
            current_hash = (
                upload_details.get("sha256")
                if upload_details is not None
                else None
            )
            if (
                not previous_hash
                or not current_hash
                or previous_hash == current_hash
            ):
                raise ValueError(
                    "This project already has a publish result; refusing to upload it again."
                )
            changed_master = True

        if attempt_path.exists():
            previous_attempt = json.loads(
                attempt_path.read_text(encoding="utf-8")
            )
            recoverable_tag_rejection = self._is_invalid_tags_rejection(
                previous_attempt
            )
            if not recoverable_tag_rejection and (
                not changed_master
                or previous_attempt.get("status") != "completed"
            ):
                raise RuntimeError(
                    "A prior upload attempt has no saved result. Reconcile its status "
                    "before retrying to avoid a duplicate upload."
                )
            if recoverable_tag_rejection and not changed_master:
                history_directory = publish_dir / "history"
                history_directory.mkdir(parents=True, exist_ok=True)
                archive = history_directory / (
                    "publish_attempt-"
                    f"{hashlib.sha256(attempt_path.read_bytes()).hexdigest()}.json"
                )
                if archive.exists():
                    raise RuntimeError(
                        "The rejected upload attempt is already archived; refusing "
                        "to overwrite upload history."
                    )
                attempt_path.replace(archive)

        if changed_master:
            history_directory = publish_dir / "history"
            history_directory.mkdir(parents=True, exist_ok=True)
            previous_records = [(result_path, "publish")]
            if attempt_path.exists():
                previous_records.append((attempt_path, "publish_attempt"))
            archive_paths = [
                (
                    source,
                    history_directory
                    / (
                        f"{prefix}-"
                        f"{hashlib.sha256(source.read_bytes()).hexdigest()}.json"
                    ),
                )
                for source, prefix in previous_records
            ]
            if any(archive.exists() for _, archive in archive_paths):
                raise RuntimeError(
                    "The previous publish record is already archived; refusing "
                    "to overwrite upload history."
                )
            for source, archive in archive_paths:
                source.replace(archive)

        attempt = {
            "status": "uploading",
            "title": title,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with attempt_path.open("x", encoding="utf-8") as file:
                json.dump(attempt, file, indent=2)
        except FileExistsError as exc:
            raise RuntimeError(
                "Another upload attempt has already claimed this project."
            ) from exc
        try:
            response = self.provider.upload_video(
                video_file=video_file,
                title=title,
                description=description,
                metadata=metadata,
                scheduled_for=schedule,
            )
        except Exception as exc:
            rejected_tags = isinstance(exc, YouTubeUploadRejected)
            failed_attempt = {
                "status": "rejected" if rejected_tags else "outcome_unknown",
                "title": title,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "error": str(exc),
            }
            if rejected_tags:
                failed_attempt["reason"] = exc.reason
            attempt_path.write_text(
                json.dumps(
                    failed_attempt,
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise

        omitted_tags = response.get("youtube_tags_omitted")
        if omitted_tags:
            upload_details = {
                **(upload_details or {}),
                "youtube_tags_submitted": response.get(
                    "youtube_tags_submitted",
                    [],
                ),
                "youtube_tags_omitted": omitted_tags,
            }

        result = PublishResult(
            publish_status="PRIVATE" if private_only else "PUBLISHED",
            video_id=response["video_id"],
            url=response["url"],
            title=title,
            scheduled_for=schedule,
            uploaded_at=datetime.now(timezone.utc).isoformat(),
            upload_details=upload_details,
        )
        self._write_json_atomically(result_path, result.to_dict())
        attempt_path.write_text(
            json.dumps(
                {
                    "status": "completed",
                    "title": title,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return result

    @staticmethod
    def _is_invalid_tags_rejection(attempt: Any) -> bool:
        if not isinstance(attempt, dict):
            return False
        if (
            attempt.get("status") == "rejected"
            and attempt.get("reason") == "invalidTags"
        ):
            return True
        error = attempt.get("error")
        return (
            attempt.get("status") == "outcome_unknown"
            and isinstance(error, str)
            and "HttpError 400" in error
            and "invalidTags" in error
        )

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

    def publish_packaged_video(
        self,
        *,
        project: Project,
        video_file: str | Path,
        artifact: PackagingArtifact,
        approved_by: str,
        scheduled_for: str | None = None,
        category: str = "Entertainment",
        language: str = "en",
        made_for_kids: bool = False,
        upload_details: dict[str, Any] | None = None,
    ) -> PublishResult:
        approval = self._load_approval(project)
        if not approval.approved:
            raise ValueError("Uploads require explicit human approval before publishing.")
        if approval.approved_by != approved_by.strip():
            raise ValueError("The supplied approver does not match the saved publish approval.")

        if artifact.selected_title.strip() and artifact.metadata.tags:
            metadata = {
                "category_id": {"Entertainment": "24", "Education": "27"}.get(category, "24"),
                "privacy_status": "private" if not scheduled_for else "private",
                "made_for_kids": bool(made_for_kids),
                "notify_subscribers": False,
                "tags": list(artifact.metadata.tags),
                "language": (language or "en").strip() or "en",
            }
        else:
            raise ValueError("Packaging artifact must include a selected title and tags before upload.")

        if scheduled_for:
            self.set_publish_schedule(project, scheduled_for)
            return self.publish_video(
                project=project,
                video_file=video_file,
                title=artifact.selected_title,
                description=artifact.metadata.description,
                metadata=metadata,
                scheduled_for=scheduled_for,
                upload_details=upload_details,
            )

        return self.publish_video(
            project=project,
            video_file=video_file,
            title=artifact.selected_title,
            description=artifact.metadata.description,
            metadata={**metadata, "privacy_status": "private"},
            upload_details=upload_details,
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
            uploaded_at=payload.get("uploaded_at"),
            upload_status=payload.get("upload_status", "UPLOAD_COMPLETE"),
            upload_details=payload.get("upload_details"),
            youtube_processing_status=payload.get(
                "youtube_processing_status",
                "YOUTUBE_PROCESSING_UNVERIFIED",
            ),
            youtube_processing_error=payload.get("youtube_processing_error"),
            youtube_details=payload.get("youtube_details"),
        )

    @staticmethod
    def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            suffix=".tmp",
            delete=False,
        ) as file:
            json.dump(payload, file, indent=2)
            file.write("\n")
            temporary_path = Path(file.name)
        temporary_path.replace(path)
