import json
from pathlib import Path

import pytest

from modules.project.manager import ProjectManager
from scripts import run_private_upload_stage, upload_youtube_thumbnail


def create_saved_publish_result(project_directory: Path, video_id: str = "existing-video"):
    publishing = project_directory / "publishing"
    publishing.mkdir(parents=True, exist_ok=True)
    (publishing / "publish.json").write_text(
        json.dumps(
            {
                "publish_status": "PRIVATE",
                "video_id": video_id,
                "url": f"https://youtu.be/{video_id}",
                "title": "Recovery test",
                "scheduled_for": None,
            }
        ),
        encoding="utf-8",
    )
    return publishing


def test_private_upload_resume_skips_video_when_publish_result_exists(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    manager = ProjectManager(Path("projects"))
    project = manager.create_project("A recovery test")
    project_directory = manager.get_project_path(project)
    create_saved_publish_result(project_directory)
    monkeypatch.setenv("RITZZ_PROJECT_ID", project.project_id)

    assert run_private_upload_stage.main() == 0


def test_thumbnail_upload_resume_skips_completed_thumbnail(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    manager = ProjectManager(Path("projects"))
    project = manager.create_project("A recovery test")
    project_directory = manager.get_project_path(project)
    publishing = project_directory / "publishing"
    publishing.mkdir(parents=True, exist_ok=True)
    create_saved_publish_result(project_directory)
    (publishing / "thumbnail_upload.json").write_text(
        json.dumps({"status": "completed", "video_id": "existing-video"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("RITZZ_PROJECT_ID", project.project_id)

    assert upload_youtube_thumbnail.main() == 0


def test_thumbnail_retry_reuses_video_id_and_skips_video_upload(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    manager = ProjectManager(Path("projects"))
    project = manager.create_project("A recovery test")
    project_directory = manager.get_project_path(project)
    publishing = create_saved_publish_result(project_directory)
    thumbnail = project_directory / "video" / "thumbnail.jpg"
    thumbnail.parent.mkdir(parents=True, exist_ok=True)
    thumbnail.write_bytes(b"thumbnail")
    (publishing / "thumbnail_upload.json").write_text(
        json.dumps({"status": "failed", "video_id": "existing-video"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("RITZZ_PROJECT_ID", project.project_id)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(tmp_path / "client.json"))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "token.json"))

    uploaded_video_ids = []

    class Provider:
        def __init__(self, *_args):
            pass

        def set_thumbnail(self, *, video_id, thumbnail_file):
            assert Path(thumbnail_file).is_file()
            uploaded_video_ids.append(video_id)
            return {"kind": "thumbnail"}

    monkeypatch.setattr(upload_youtube_thumbnail, "YouTubeProvider", Provider)
    monkeypatch.setattr(
        run_private_upload_stage.PublishingEngine,
        "publish_packaged_video",
        lambda *_args, **_kwargs: pytest.fail("Video upload must not be repeated."),
    )

    assert run_private_upload_stage.main() == 0
    assert upload_youtube_thumbnail.main() == 0
    assert uploaded_video_ids == ["existing-video"]
    marker = json.loads((publishing / "thumbnail_upload.json").read_text(encoding="utf-8"))
    assert marker["status"] == "completed"
    assert marker["video_id"] == "existing-video"


def test_supplied_thumbnail_is_used_instead_of_generated_thumbnail(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    manager = ProjectManager(Path("projects"))
    project = manager.create_project("A supplied thumbnail test")
    project_directory = manager.get_project_path(project)
    create_saved_publish_result(project_directory)
    supplied = project_directory / "thumbnail" / "supplied_thumbnail.png"
    supplied.parent.mkdir(parents=True, exist_ok=True)
    supplied.write_bytes(b"supplied thumbnail")
    generated = project_directory / "video" / "thumbnail.jpg"
    generated.write_bytes(b"generated thumbnail")
    monkeypatch.setenv("RITZZ_PROJECT_ID", project.project_id)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRETS_FILE", str(tmp_path / "client.json"))
    monkeypatch.setenv("GOOGLE_TOKEN_FILE", str(tmp_path / "token.json"))
    uploaded_paths = []

    class Provider:
        def __init__(self, *_args):
            pass

        def set_thumbnail(self, *, video_id, thumbnail_file):
            uploaded_paths.append(Path(thumbnail_file))
            return {"kind": "thumbnail"}

    monkeypatch.setattr(upload_youtube_thumbnail, "YouTubeProvider", Provider)

    assert upload_youtube_thumbnail.main() == 0

    assert uploaded_paths == [supplied]


def test_completed_thumbnail_marker_must_match_saved_video_id(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    manager = ProjectManager(Path("projects"))
    project = manager.create_project("A recovery test")
    project_directory = manager.get_project_path(project)
    publishing = create_saved_publish_result(project_directory)
    (publishing / "thumbnail_upload.json").write_text(
        json.dumps({"status": "completed", "video_id": "different-video"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("RITZZ_PROJECT_ID", project.project_id)

    with pytest.raises(RuntimeError, match="different video ID"):
        upload_youtube_thumbnail.main()
