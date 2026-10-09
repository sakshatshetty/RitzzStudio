from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from modules.project.packaging import fit_youtube_tags


class YouTubeUploadRejected(RuntimeError):
    """The YouTube API definitively rejected request metadata before upload."""

    reason = "invalidTags"


class YouTubeProvider:
    """Uploads videos through the YouTube Data API using local OAuth credentials."""

    SCOPES: ClassVar[list[str]] = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    ]

    def __init__(
        self,
        credentials_file: str | Path,
        token_file: str | Path,
        *,
        service: Any | None = None,
        service_builder: Callable[[str | Path, str | Path, list[str]], Any] | None = None,
        media_upload_builder: Callable[[str], Any] | None = None,
    ):
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self._service = service
        self._service_builder = service_builder or self._build_service
        self._media_upload_builder = media_upload_builder or self._build_media_upload

    @property
    def service(self) -> Any:
        if self._service is None:
            self._service = self._service_builder(
                self.credentials_file,
                self.token_file,
                self.SCOPES,
            )
        return self._service

    def upload_video(
        self,
        *,
        video_file: str | Path,
        title: str,
        description: str,
        metadata: dict[str, Any],
        scheduled_for: str | None = None,
    ) -> dict[str, Any]:
        video_path = Path(video_file)
        if not video_path.is_file():
            raise FileNotFoundError(f"Video file does not exist: {video_path}")

        snippet: dict[str, Any] = {
            "title": title,
            "description": description,
            "categoryId": str(metadata.get("category_id", "27")),
        }
        raw_tags = metadata.get("tags", [])
        if not isinstance(raw_tags, list):
            raise ValueError("YouTube tags must be supplied as a list of strings.")
        submitted_tags, omitted_tags = fit_youtube_tags(raw_tags)
        if submitted_tags:
            snippet["tags"] = submitted_tags

        status = {
            "privacyStatus": "private" if scheduled_for else metadata.get("privacy_status", "private"),
            "selfDeclaredMadeForKids": bool(metadata.get("made_for_kids", False)),
        }
        if scheduled_for:
            status["publishAt"] = scheduled_for

        request = self.service.videos().insert(
            part="snippet,status",
            body={"snippet": snippet, "status": status},
            media_body=self._media_upload_builder(str(video_path)),
            notifySubscribers=bool(metadata.get("notify_subscribers", True)),
        )
        try:
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise RuntimeError(
                "YouTube uploads require google-api-python-client."
            ) from exc
        try:
            response = request.execute()
        except HttpError as exc:
            if (
                getattr(exc.resp, "status", None) == 400
                and self._is_invalid_tags_error(exc)
            ):
                raise YouTubeUploadRejected(
                    "YouTube rejected the upload metadata with invalidTags; "
                    "the video was not created."
                ) from exc
            raise
        video_id = response["id"]
        result: dict[str, Any] = {
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
        }
        if omitted_tags:
            result["youtube_tags_submitted"] = submitted_tags
            result["youtube_tags_omitted"] = omitted_tags
        return result

    @staticmethod
    def _is_invalid_tags_error(error: Any) -> bool:
        content = getattr(error, "content", None)
        if isinstance(content, bytes):
            try:
                content = content.decode("utf-8")
            except UnicodeDecodeError:
                return False
        if not isinstance(content, str):
            return False
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        error_payload = payload.get("error")
        if not isinstance(error_payload, dict):
            return False
        details = error_payload.get("errors", [])
        if not isinstance(details, list):
            return False
        return any(
            isinstance(item, dict) and item.get("reason") == "invalidTags"
            for item in details
        )

    def set_thumbnail(
        self,
        *,
        video_id: str,
        thumbnail_file: str | Path,
    ) -> dict[str, Any]:
        thumbnail_path = Path(thumbnail_file)
        if not video_id.strip():
            raise ValueError("A YouTube video ID is required to set its thumbnail.")
        if not thumbnail_path.is_file() or thumbnail_path.stat().st_size == 0:
            raise FileNotFoundError(
                f"Thumbnail image is missing or empty: {thumbnail_path}"
            )
        request = self.service.thumbnails().set(
            videoId=video_id,
            media_body=self._media_upload_builder(str(thumbnail_path)),
        )
        return request.execute()

    def get_video_processing_status(self, video_id: str) -> dict[str, Any]:
        if not video_id.strip():
            raise ValueError("A YouTube video ID is required for status verification.")
        try:
            from google.auth.exceptions import TransportError
            from googleapiclient.errors import HttpError
        except ImportError as exc:
            raise RuntimeError(
                "YouTube status verification requires google-auth and "
                "google-api-python-client."
            ) from exc
        try:
            response = (
                self.service.videos()
                .list(
                    part="contentDetails,processingDetails,snippet,status",
                    id=video_id,
                )
                .execute()
            )
        except (HttpError, TransportError, OSError) as exc:
            return {
                "processing_status": "YOUTUBE_PROCESSING_UNAVAILABLE",
                "verification_error": str(exc),
            }

        items = response.get("items", [])
        if not items:
            return {
                "processing_status": "YOUTUBE_PROCESSING_UNAVAILABLE",
                "verification_error": "YouTube returned no video details.",
            }
        video = items[0]
        processing = video.get("processingDetails", {})
        raw_status = processing.get("processingStatus")
        status_mapping = {
            "processing": "YOUTUBE_PROCESSING_PENDING",
            "succeeded": "YOUTUBE_PROCESSING_SUCCEEDED",
            "failed": "YOUTUBE_PROCESSING_FAILED",
            "terminated": "YOUTUBE_PROCESSING_FAILED",
        }
        result: dict[str, Any] = {
            "processing_status": status_mapping.get(
                raw_status,
                "YOUTUBE_PROCESSING_UNAVAILABLE",
            ),
            "video_id": video.get("id", video_id),
            "title": video.get("snippet", {}).get("title"),
            "privacy_status": video.get("status", {}).get("privacyStatus"),
            "duration": video.get("contentDetails", {}).get("duration"),
        }
        if result["processing_status"] == "YOUTUBE_PROCESSING_FAILED":
            result["processing_error"] = processing.get(
                "processingFailureReason",
                "YouTube reported video processing failure.",
            )
        elif result["processing_status"] == "YOUTUBE_PROCESSING_UNAVAILABLE":
            result["verification_error"] = (
                f"YouTube returned an unknown processing status: {raw_status!r}."
            )
        return result

    @staticmethod
    def _build_media_upload(video_file: str) -> Any:
        try:
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:
            raise RuntimeError(
                "YouTube publishing requires google-api-python-client. "
                "Install the project requirements before selecting YouTubeProvider."
            ) from exc
        return MediaFileUpload(video_file, resumable=True)

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
                "YouTube publishing requires google-api-python-client, google-auth, "
                "and google-auth-oauthlib. Install the project requirements first."
            ) from exc

        credentials: Any | None = None
        token_path = Path(token_file)
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

        return build("youtube", "v3", credentials=credentials)