from pathlib import Path

import pytest

from modules.project.manager import ProjectManager
from modules.publishing.engine import PublishingEngine, FakeYouTubeProvider


def test_publish_requires_approval_before_upload(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Why Do Pirates Wear Eye Patches?")
    engine = PublishingEngine(tmp_path / "projects", provider=FakeYouTubeProvider())

    with pytest.raises(ValueError, match="approval"):
        engine.publish_video(
            project=project,
            video_file=tmp_path / "video.mp4",
            title="Why Do Pirates Wear Eye Patches? The Surprising Medical Reason",
            description="A curious explainer about sailors and sunlight.",
            metadata={"category": "Education"},
        )


def test_publish_writes_result_and_stores_video_metadata(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    manager = ProjectManager(projects_dir)
    project = manager.create_project("Why Do Pirates Wear Eye Patches?")

    project_folder = projects_dir / f"{project.project_id}_{project.slug}"
    video_file = project_folder / "video" / "final.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"video")

    engine = PublishingEngine(projects_dir, provider=FakeYouTubeProvider())
    engine.create_approval(project, approved=True, approved_by="human")
    engine.set_publish_schedule(project, "2026-09-30T12:00:00+00:00")

    result = engine.publish_video(
        project=project,
        video_file=video_file,
        title="Why Do Pirates Wear Eye Patches? The Surprising Medical Reason",
        description="Sailors used eye patches to help one eye adjust to bright sunlight after long nights below deck.",
        metadata={"category": "Education", "tags": ["pirates", "history", "science"]},
    )

    assert result.publish_status == "PUBLISHED"
    assert result.video_id
    assert result.url.startswith("https://youtu.be/")
    assert (project_folder / "publishing" / "publish.json").exists()


def test_publish_schedule_can_be_set_and_saved_per_project(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    manager = ProjectManager(projects_dir)
    project = manager.create_project("Why Do Pirates Wear Eye Patches?")

    engine = PublishingEngine(projects_dir, provider=FakeYouTubeProvider())
    engine.create_approval(project, approved=True, approved_by="human")
    engine.set_publish_schedule(project, "2026-09-30T12:00:00+00:00")

    schedule = engine.load_publish_schedule(project)
    assert schedule == "2026-09-30T12:00:00+00:00"

    project_folder = projects_dir / f"{project.project_id}_{project.slug}"
    publish_file = project_folder / "publishing" / "schedule.json"
    assert publish_file.exists()


def test_publish_workflow_requires_approval_and_schedule_before_upload(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    manager = ProjectManager(projects_dir)
    project = manager.create_project("Why Do Pirates Wear Eye Patches?")

    project_folder = projects_dir / f"{project.project_id}_{project.slug}"
    video_file = project_folder / "video" / "final.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"video")

    engine = PublishingEngine(projects_dir, provider=FakeYouTubeProvider())
    with pytest.raises(ValueError, match="approval"):
        engine.publish_video(
            project=project,
            video_file=video_file,
            title="Why Do Pirates Wear Eye Patches? The Surprising Medical Reason",
            description="Sailors used eye patches to help one eye adjust to daylight.",
            metadata={"category": "Education"},
        )

    engine.create_approval(project, approved=True, approved_by="human")
    with pytest.raises(ValueError, match="schedule"):
        engine.publish_video(
            project=project,
            video_file=video_file,
            title="Why Do Pirates Wear Eye Patches? The Surprising Medical Reason",
            description="Sailors used eye patches to help one eye adjust to daylight.",
            metadata={"category": "Education"},
        )

    engine.set_publish_schedule(project, "2026-09-30T12:00:00+00:00")
    result = engine.publish_video(
        project=project,
        video_file=video_file,
        title="Why Do Pirates Wear Eye Patches? The Surprising Medical Reason",
        description="Sailors used eye patches to help one eye adjust to daylight.",
        metadata={"category": "Education"},
    )

    assert result.publish_status == "PUBLISHED"
    assert result.scheduled_for == "2026-09-30T12:00:00+00:00"


def test_publish_workflow_runs_as_single_orchestrated_action(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    manager = ProjectManager(projects_dir)
    project = manager.create_project("Why Do Pirates Wear Eye Patches?")

    project_folder = projects_dir / f"{project.project_id}_{project.slug}"
    video_file = project_folder / "video" / "final.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"video")

    engine = PublishingEngine(projects_dir, provider=FakeYouTubeProvider())
    engine.create_approval(project, approved=True, approved_by="human")
    result = engine.publish_project(
        project=project,
        video_file=video_file,
        title="Why Do Pirates Wear Eye Patches? The Surprising Medical Reason",
        description="Sailors used eye patches to help one eye adjust to daylight.",
        metadata={"category": "Education"},
        approved_by="human",
        scheduled_for="2026-09-30T12:00:00+00:00",
    )

    assert result.publish_status == "PUBLISHED"
    assert engine.load_publish_schedule(project) == "2026-09-30T12:00:00+00:00"
    assert (project_folder / "publishing" / "approval.json").exists()
    assert (project_folder / "publishing" / "publish.json").exists()


def test_project_orchestration_cannot_create_its_own_approval(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    manager = ProjectManager(projects_dir)
    project = manager.create_project("Why Do Pirates Wear Eye Patches?")
    project_folder = projects_dir / f"{project.project_id}_{project.slug}"
    video_file = project_folder / "video" / "final.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"video")

    provider = FakeYouTubeProvider()
    engine = PublishingEngine(projects_dir, provider=provider)

    with pytest.raises(ValueError, match="approval"):
        engine.publish_project(
            project=project,
            video_file=video_file,
            title="A title",
            description="A description",
            metadata={},
            approved_by="human",
            scheduled_for="2026-09-30T12:00:00+00:00",
        )

    assert provider.calls == []
    assert not (project_folder / "publishing" / "approval.json").exists()
    assert not (project_folder / "publishing" / "publish.json").exists()


def test_project_orchestration_requires_approver_to_match_saved_approval(tmp_path: Path):
    projects_dir = tmp_path / "projects"
    manager = ProjectManager(projects_dir)
    project = manager.create_project("Why Do Pirates Wear Eye Patches?")
    project_folder = projects_dir / f"{project.project_id}_{project.slug}"
    video_file = project_folder / "video" / "final.mp4"
    video_file.parent.mkdir(parents=True, exist_ok=True)
    video_file.write_bytes(b"video")

    provider = FakeYouTubeProvider()
    engine = PublishingEngine(projects_dir, provider=provider)
    engine.create_approval(project, approved=True, approved_by="reviewer")

    with pytest.raises(ValueError, match="does not match"):
        engine.publish_project(
            project=project,
            video_file=video_file,
            title="A title",
            description="A description",
            metadata={},
            approved_by="other-user",
            scheduled_for="2026-09-30T12:00:00+00:00",
        )

    assert provider.calls == []
    assert engine.load_publish_schedule(project) is None


def test_approved_publish_artifact_requires_approver_identity(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Why Do Pirates Wear Eye Patches?")
    engine = PublishingEngine(tmp_path / "projects", provider=FakeYouTubeProvider())

    with pytest.raises(ValueError, match="approving user"):
        engine.create_approval(project, approved=True, approved_by="  ")
