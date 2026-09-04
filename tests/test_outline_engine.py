import json

from modules.outline.engine import OutlineEngine
from modules.outline.models import Outline, OutlineSection


def test_save_and_load_outline(tmp_path):
    engine = OutlineEngine.__new__(OutlineEngine)

    outline = Outline(
        topic="Test Topic",
        target_duration_seconds=480,
        hook="This is the hook.",
        sections=[
            OutlineSection(
                section_id="section_001",
                section_type="hook",
                title="The Hook",
                purpose="Create curiosity.",
                key_points=["Point one"],
                estimated_seconds=60,
                research_sources=["source_001"],
            )
        ],
        total_estimated_seconds=60,
        closing_message="This is the conclusion.",
    )

    outline_file = tmp_path / "outline.json"

    engine._save_outline(
        outline_file,
        outline,
    )

    assert outline_file.exists()

    loaded = engine._load_outline(
        outline_file
    )

    assert isinstance(loaded, Outline)
    assert loaded.topic == "Test Topic"
    assert loaded.sections[0].title == "The Hook"


def test_outline_duration_validation():
    engine = OutlineEngine.__new__(OutlineEngine)

    outline = Outline(
        topic="Test Topic",
        target_duration_seconds=480,
        hook="Hook",
        sections=[
            OutlineSection(
                section_id="section_001",
                section_type="hook",
                title="Hook",
                purpose="Create curiosity.",
                estimated_seconds=120,
            ),
            OutlineSection(
                section_id="section_002",
                section_type="explanation",
                title="Explanation",
                purpose="Explain the topic.",
                estimated_seconds=180,
            ),
            OutlineSection(
                section_id="section_003",
                section_type="conclusion",
                title="Conclusion",
                purpose="Close the story.",
                estimated_seconds=180,
            ),
        ],
        total_estimated_seconds=480,
        closing_message="Conclusion",
    )

    engine._validate_duration(outline)


def test_outline_duration_mismatch():
    engine = OutlineEngine.__new__(OutlineEngine)

    outline = Outline(
        topic="Test Topic",
        target_duration_seconds=480,
        hook="Hook",
        sections=[
            OutlineSection(
                section_id="section_001",
                section_type="hook",
                title="Hook",
                purpose="Create curiosity.",
                estimated_seconds=100,
            )
        ],
        total_estimated_seconds=200,
        closing_message="Conclusion",
    )

    try:
        engine._validate_duration(outline)
    except ValueError:
        return

    raise AssertionError(
        "Expected duration mismatch to raise ValueError"
    )


def test_outline_file_contains_valid_json(tmp_path):
    engine = OutlineEngine.__new__(OutlineEngine)

    outline = Outline(
        topic="Test Topic",
        target_duration_seconds=480,
        hook="Hook",
        sections=[],
        total_estimated_seconds=0,
        closing_message="Conclusion",
    )

    outline_file = tmp_path / "outline.json"

    engine._save_outline(
        outline_file,
        outline,
    )

    data = json.loads(
        outline_file.read_text(
            encoding="utf-8"
        )
    )

    assert data["topic"] == "Test Topic"