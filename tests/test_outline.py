from modules.outline.models import Outline, OutlineSection


def test_outline_model():
    outline = Outline(
        topic="Why Do Pirates Wear Eye Patches?",
        hook="The real reason pirates wore eye patches may not be what you think.",
        sections=[
            OutlineSection(
                section_id="section_001",
                section_type="hook",
                title="The Eye Patch Mystery",
                purpose="Create curiosity.",
                key_points=[
                    "Pirate eye patches are iconic.",
                    "The popular explanation may be wrong.",
                ],
                estimated_seconds=25,
                research_sources=["source_001"],
            ),
            OutlineSection(
                section_id="section_002",
                section_type="setup",
                title="The Popular Theory",
                purpose="Introduce the commonly believed explanation.",
                key_points=[
                    "Dark adaptation theory.",
                ],
                estimated_seconds=40,
                research_sources=["source_002"],
            ),
        ],
        total_estimated_seconds=65,
        closing_message="The truth is more complicated than the legend.",
    )

    assert outline.topic == "Why Do Pirates Wear Eye Patches?"
    assert outline.target_duration_seconds == 480
    assert len(outline.sections) == 2
    assert outline.sections[0].section_type == "hook"


def test_outline_section_validation():
    section = OutlineSection(
        section_id="section_001",
        section_type="explanation",
        title="Explanation",
        purpose="Explain the evidence.",
        estimated_seconds=60,
    )

    assert section.estimated_seconds == 60
    assert section.key_points == []
    assert section.research_sources == []