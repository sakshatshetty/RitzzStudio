from pathlib import Path
from typing import Any

from modules.publishing.youtube_provider import YouTubeProvider


class FakeRequest:
    def __init__(self, response: dict[str, str]):
        self.response = response

    def execute(self) -> dict[str, str]:
        return self.response


class FakeVideos:
    def __init__(self):
        self.insert_args: dict[str, Any] | None = None

    def insert(self, **kwargs: Any):
        self.insert_args = kwargs
        return FakeRequest({"id": "abc123"})


class FakeThumbnails:
    def __init__(self):
        self.set_args: dict[str, Any] | None = None

    def set(self, **kwargs: Any):
        self.set_args = kwargs
        return FakeRequest({"kind": "youtube#thumbnailSetResponse"})


class FakeService:
    def __init__(self):
        self.video_resource = FakeVideos()
        self.thumbnail_resource = FakeThumbnails()

    def videos(self):
        return self.video_resource

    def thumbnails(self):
        return self.thumbnail_resource


def test_youtube_provider_maps_metadata_and_schedule_without_network(tmp_path: Path):
    video_file = tmp_path / "final.mp4"
    video_file.write_bytes(b"video")
    service = FakeService()
    media_file = object()

    provider = YouTubeProvider(
        tmp_path / "client-secret.json",
        tmp_path / "token.json",
        service=service,
        media_upload_builder=lambda path: media_file,
    )

    result = provider.upload_video(
        video_file=video_file,
        title="A title",
        description="A description",
        metadata={
            "category_id": "27",
            "tags": ["history", "science"],
            "privacy_status": "public",
            "notify_subscribers": False,
        },
        scheduled_for="2026-09-30T12:00:00+00:00",
    )

    request = service.video_resource.insert_args
    assert request is not None
    assert result == {"video_id": "abc123", "url": "https://youtu.be/abc123"}
    assert request["part"] == "snippet,status"
    assert request["body"] == {
        "snippet": {
            "title": "A title",
            "description": "A description",
            "categoryId": "27",
            "tags": ["history", "science"],
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
            "publishAt": "2026-09-30T12:00:00+00:00",
        },
    }
    assert request["media_body"] is media_file
    assert request["notifySubscribers"] is False


def test_youtube_provider_sets_thumbnail_without_network(tmp_path: Path):
    thumbnail = tmp_path / "thumbnail.jpg"
    thumbnail.write_bytes(b"image")
    service = FakeService()
    media_file = object()
    provider = YouTubeProvider(
        tmp_path / "client-secret.json",
        tmp_path / "token.json",
        service=service,
        media_upload_builder=lambda _path: media_file,
    )

    response = provider.set_thumbnail(
        video_id="abc123",
        thumbnail_file=thumbnail,
    )

    assert response == {"kind": "youtube#thumbnailSetResponse"}
    assert service.thumbnail_resource.set_args is not None
    assert service.thumbnail_resource.set_args == {
        "videoId": "abc123",
        "media_body": media_file,
    }