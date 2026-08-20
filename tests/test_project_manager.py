from pathlib import Path

import pytest

from modules.project.manager import ProjectManager


def test_create_project(tmp_path: Path):
    manager = ProjectManager(tmp_path)

    project = manager.create_project(
        "Why Do Pirates Wear Eye Patches?"
    )

    project_path = manager.get_project_path(project)

    assert project.project_id.startswith("20")
    assert project.slug == "why_do_pirates_wear_eye_patches"

    assert project_path.exists()
    assert (project_path / "project.json").exists()

    for directory in manager.PROJECT_DIRECTORIES:
        assert (project_path / directory).exists()


def test_load_project(tmp_path: Path):
    manager = ProjectManager(tmp_path)

    created = manager.create_project(
        "Why Are Bananas Curved?"
    )

    loaded = manager.load_project(created.project_id)

    assert loaded.project_id == created.project_id
    assert loaded.title == "Why Are Bananas Curved?"
    assert loaded.slug == "why_are_bananas_curved"


def test_update_status(tmp_path: Path):
    manager = ProjectManager(tmp_path)

    project = manager.create_project(
        "Why Do Cats Purr?"
    )

    updated = manager.update_status(
        project.project_id,
        "research",
    )

    assert updated.status == "research"


def test_complete_step(tmp_path: Path):
    manager = ProjectManager(tmp_path)

    project = manager.create_project(
        "Why Is The Sky Blue?"
    )

    updated = manager.complete_step(
        project.project_id,
        "research",
    )

    assert updated.steps["research"] is True
    assert updated.status == "research_completed"


def test_unknown_step_fails(tmp_path: Path):
    manager = ProjectManager(tmp_path)

    project = manager.create_project(
        "Test Project"
    )

    with pytest.raises(ValueError):
        manager.complete_step(
            project.project_id,
            "invalid_step",
        )