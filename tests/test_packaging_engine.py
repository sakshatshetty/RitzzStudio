from pathlib import Path

import pytest

from modules.project.manager import ProjectManager
from modules.project.packaging import PackagingEngine
from modules.topic_intelligence.models import OpportunityCandidate


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


def test_vidiq_candidate_informs_packaging_and_is_persisted(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Why Do Pirates Wear Eye Patches?")
    engine = PackagingEngine(tmp_path)
    candidate = OpportunityCandidate(
        candidate_id="candidate-1",
        topic="Why Do Pirates Wear Eye Patches?",
        proposed_title="Why Pirates Wear Eye Patches: The Real Reason",
        angle="the practical adaptation sailors used between darkness and sunlight",
        primary_keyword="pirate eye patch",
        related_keywords=["pirate history", "sailor vision"],
        related_questions=["Did eye patches improve night vision?"],
        provider="vidiq",
    )

    artifact = engine.build_project_packaging(
        project=project,
        topic=candidate.topic,
        script_excerpt="Sailors moved between dark decks and bright sunlight.",
        opportunity_context={
            "report_id": "report-1",
            "provider": candidate.provider,
            **candidate.model_dump(mode="json"),
        },
    )

    assert artifact.selected_title == candidate.proposed_title
    assert "pirate" in " ".join(artifact.metadata.tags).lower()
    assert "adaptation" in artifact.metadata.description
    assert artifact.opportunity_context["report_id"] == "report-1"
    assert artifact.thumbnail_brief is not None
    assert "adaptation" in artifact.thumbnail_brief.notes

    saved = (manager.get_project_path(project) / "packaging.json").read_text(encoding="utf-8")
    assert '"opportunity_context"' in saved


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


def test_build_upload_metadata_uses_entertainment_category_and_language_defaults(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Why do pirates wear eye patches?")
    engine = PackagingEngine(tmp_path)

    artifact = engine.build_project_packaging(
        project=project,
        topic="Why do pirates wear eye patches?",
        script_excerpt="Sailors used eye patches to help one eye adjust to daylight after long nights below deck.",
        selected_title="Why Do Pirates Wear Eye Patches? The Surprising Medical Reason",
        category="Entertainment",
        language="en",
        made_for_kids=False,
    )

    payload = engine.build_upload_metadata(artifact, category="Entertainment", language="en", made_for_kids=False)
    assert payload["title"] == artifact.selected_title
    assert payload["tags"] == artifact.metadata.tags
    assert payload["description"] == artifact.metadata.description
    assert payload["category_id"] == "24"
    assert payload["language"] == "en"
    assert payload["made_for_kids"] is False
    assert len(artifact.title_options) >= 3
