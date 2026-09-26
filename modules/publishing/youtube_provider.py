from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class YouTubeProvider:
    """Uploads videos through the YouTube Data API using local OAuth credentials."""

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

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

        snippet = {
            "title": title,
            "description": description,
            "categoryId": str(metadata.get("category_id", "27")),
        }
        if metadata.get("tags"):
            snippet["tags"] = list(metadata["tags"])

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
        response = request.execute()
        video_id = response["id"]
        return {
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
        }

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