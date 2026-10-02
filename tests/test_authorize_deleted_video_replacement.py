import json
from pathlib import Path

import pytest

from modules.production_state import ProductionStateStore
from modules.project.manager import ProjectManager
from scripts import authorize_deleted_video_replacement


def set_up_replacement_case(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = ProjectManager(Path("projects"))
    project = manager.create_project("Replacement upload test")
    project_directory = manager.get_project_path(project)
    publishing = project_directory / "publishing"
    publishing.mkdir(parents=True, exist_ok=True)
    (publishing / "publish.json").write_text(
        json.dumps(
            {
                "publish_status": "PRIVATE",
                "video_id": "deletedVideo123",
                "url": "https://youtu.be/deletedVideo123",
                "title": "Existing private test",
                "scheduled_for": None,
            }
        ),
        encoding="utf-8",
    )
    (publishing / "publish_attempt.json").write_text(
        json.dumps({"status": "completed"}),
        encoding="utf-8",
    )
    (publishing / "thumbnail_upload.json").write_text(
        json.dumps({"status": "completed", "video_id": "deletedVideo123"}),
        encoding="utf-8",
    )
    state_file = tmp_path / ".pipeline-artifacts" / "production_state.json"
    store = ProductionStateStore(state_file)
    store.initialize("prod-123")
    store.start_stage("private_upload")
    store.set_private_upload_intent("prior-run", 1)
    monkeypatch.setenv("RITZZ_PRODUCTION_ID", "prod-123")
    monkeypatch.setenv("RITZZ_PROJECT_ID", project.project_id)
    monkeypatch.setenv("RITZZ_PRODUCTION_STATE_FILE", str(state_file))
    monkeypatch.setenv("RITZZ_PIPELINE_ARTIFACTS", str(state_file.parent))
    monkeypatch.setenv("GITHUB_RUN_ID", "current-run")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setenv("GITHUB_ACTOR", "reviewer")
    return publishing, store


def test_replacement_requires_explicit_deletion_confirmation(tmp_path, monkeypatch):
    publishing, _ = set_up_replacement_case(tmp_path, monkeypatch)
    monkeypatch.setenv("RITZZ_CONFIRM_DELETED_VIDEO", "false")

    with pytest.raises(ValueError, match="requires the workflow confirmation"):
        authorize_deleted_video_replacement.main()

    assert (publishing / "publish.json").is_file()
    assert (publishing / "publish_attempt.json").is_file()
    assert (publishing / "thumbnail_upload.json").is_file()


def test_confirmed_deleted_video_records_old_result_and_authorizes_new_attempt(
    tmp_path,
    monkeypatch,
):
    publishing, store = set_up_replacement_case(tmp_path, monkeypatch)
    monkeypatch.setenv("RITZZ_CONFIRM_DELETED_VIDEO", "true")

    assert authorize_deleted_video_replacement.main() == 0

    assert not (publishing / "publish.json").exists()
    assert not (publishing / "publish_attempt.json").exists()
    assert not (publishing / "thumbnail_upload.json").exists()
    archive_directory = next((publishing / "replaced_uploads").iterdir())
    assert json.loads((archive_directory / "publish.json").read_text())["video_id"] == (
        "deletedVideo123"
    )
    authorization = json.loads(
        (archive_directory / "replacement_authorization.json").read_text()
    )
    assert authorization["previous_video_id"] == "deletedVideo123"
    assert authorization["confirmed_deleted_by"] == "reviewer"

    state = store.resume("prod-123")
    assert state["private_upload_intent"]["run_id"] == "current-run"
    assert state["private_upload_intent"]["run_attempt"] == 2
    assert state["private_upload_intent"]["replacement"]["deleted_video_id"] == (
        "deletedVideo123"
    )


def test_uncertain_previous_upload_cannot_be_replaced(tmp_path, monkeypatch):
    publishing, _ = set_up_replacement_case(tmp_path, monkeypatch)
    (publishing / "publish_attempt.json").write_text(
        json.dumps({"status": "outcome_unknown"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("RITZZ_CONFIRM_DELETED_VIDEO", "true")

    with pytest.raises(RuntimeError, match="outcome may be uncertain"):
        authorize_deleted_video_replacement.main()

    assert (publishing / "publish.json").is_file()
    assert not (publishing / "replaced_uploads").exists()
