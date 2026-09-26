from pathlib import Path

import pytest

from modules.project.manager import ProjectManager
from modules.project.packaging import PackagingEngine


def test_generate_title_options_returns_distinct_titles(tmp_path: Path):
    engine = PackagingEngine(tmp_path)

    options = engine.generate_title_options(
        topic="Why do pirates wear eye patches?",
        script_excerpt="The idea was partly medical, not just pirate fashion. Eye patches helped sailors adapt to sunlight after one eye was used in dim conditions.",
    )

    assert len(options) >= 3
    assert len({option.title.casefold() for option in options}) == len(options)
    assert all(option.reason for option in options)
    assert all(option.title.strip() for option in options)


def test_build_project_packaging_writes_metadata_and_selection(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Why do pirates wear eye patches?")
    engine = PackagingEngine(tmp_path)

    artifact = engine.build_project_packaging(
        project=project,
        topic="Why do pirates wear eye patches?",
        script_excerpt="The medical origin is surprisingly practical: sailors used an eye patch to help one eye adjust to sunlight after spending time in the dark below deck.",
        selected_title="Why Do Pirates Wear Eye Patches? The Surprising Medical Reason",
    )

    project_path = manager.get_project_path(project)
    saved = (project_path / "packaging.json").read_text(encoding="utf-8")
    assert '"selected_title"' in saved
    assert artifact.selected_title == "Why Do Pirates Wear Eye Patches? The Surprising Medical Reason"
    assert artifact.metadata.description
    assert artifact.metadata.tags
    assert artifact.metadata.category == "Education"


def test_select_title_and_generate_thumbnail_brief(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Why do pirates wear eye patches?")
    engine = PackagingEngine(tmp_path)

    artifact = engine.build_project_packaging(
        project=project,
        topic="Why do pirates wear eye patches?",
        script_excerpt="Sailors spent long nights below deck, so one eye adapted to darkness while the other stayed adjusted to sunlight.",
    )

    selected = engine.select_title(project, artifact.title_options[0].title)
    assert selected == artifact.title_options[0].title

    brief = engine.generate_thumbnail_brief(
        project=project,
        topic="Why do pirates wear eye patches?",
        selected_title=selected,
        script_excerpt="Sailors spent long nights below deck, so one eye adapted to darkness while the other stayed adjusted to sunlight.",
    )

    assert brief.subject
    assert brief.primary_visual
    assert brief.mobile_readability
    assert "mobile" in brief.mobile_readability.lower()


def test_validate_packaging_metadata_requires_topic_accuracy(tmp_path: Path):
    engine = PackagingEngine(tmp_path)

    valid = engine.validate_packaging_metadata(
        topic="Why do pirates wear eye patches?",
        selected_title="Why Do Pirates Wear Eye Patches? The Surprising Medical Reason",
        description="Sailors used eye patches to help one eye adjust to daylight after long nights below deck.",
        tags=["pirates", "eye patch", "history", "medical"],
    )
    assert valid["status"] == "PASS"

    with pytest.raises(ValueError, match="topic"):
        engine.validate_packaging_metadata(
            topic="Why do pirates wear eye patches?",
            selected_title="The Secret Life of Bananas",
            description="This video explains a banana mystery.",
            tags=["bananas", "science"],
        )
