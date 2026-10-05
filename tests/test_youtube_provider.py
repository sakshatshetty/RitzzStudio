from pathlib import Path
from typing import Any

import pytest

from modules.publishing.youtube_provider import YouTubeProvider


class FakeRequest:
    def __init__(self, response: dict[str, str]):
        self.response = response

    def execute(self) -> dict[str, str]:
        return self.response


class FakeVideos:
    def __init__(self, list_response=None):
        self.insert_args: dict[str, Any] | None = None
        self.list_args: dict[str, Any] | None = None
        self.list_response = list_response or {"items": []}
        self.list_calls = 0

    def insert(self, **kwargs: Any):
        self.insert_args = kwargs
        return FakeRequest({"id": "abc123"})

    def list(self, **kwargs: Any):
        self.list_args = kwargs
        self.list_calls += 1
        return FakeRequest(self.list_response)


class FakeThumbnails:
    def __init__(self):
        self.set_args: dict[str, Any] | None = None

    def set(self, **kwargs: Any):
        self.set_args = kwargs
        return FakeRequest({"kind": "youtube#thumbnailSetResponse"})


class FakeService:
    def __init__(self, list_response=None):
        self.video_resource = FakeVideos(list_response)
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


@pytest.mark.parametrize(
    ("processing_status", "expected_status", "expected_error"),
    [
        ("processing", "YOUTUBE_PROCESSING_PENDING", None),
        ("succeeded", "YOUTUBE_PROCESSING_SUCCEEDED", None),
        (
            "failed",
            "YOUTUBE_PROCESSING_FAILED",
            "transcode failure",
        ),
        (
            "terminated",
            "YOUTUBE_PROCESSING_FAILED",
            "transcode failure",
        ),
    ],
)
def test_youtube_provider_checks_processing_once_and_reports_status(
    tmp_path: Path,
    processing_status,
    expected_status,
    expected_error,
):
    service = FakeService(
        {
            "items": [
                {
                    "id": "abc123",
                    "snippet": {"title": "Test video"},
                    "status": {"privacyStatus": "private"},
                    "contentDetails": {"duration": "PT8M"},
                    "processingDetails": {
                        "processingStatus": processing_status,
                        "processingFailureReason": "transcode failure",
                    },
                }
            ]
        }
    )
    provider = YouTubeProvider(
        tmp_path / "client-secret.json",
        tmp_path / "token.json",
        service=service,
    )

    status = provider.get_video_processing_status("abc123")

    assert status["processing_status"] == expected_status
    assert status.get("processing_error") == expected_error
    assert status["video_id"] == "abc123"
    assert status["duration"] == "PT8M"
    assert service.video_resource.list_args == {
        "part": "contentDetails,processingDetails,snippet,status",
        "id": "abc123",
    }
    assert service.video_resource.list_calls == 1