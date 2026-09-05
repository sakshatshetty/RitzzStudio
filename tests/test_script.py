import pytest

from modules.script.models import Script, ScriptSection


def test_script_model():
    section = ScriptSection(
        section_id="s1",
        section_type="hook",
        title="The Hook",
        narration="This is the opening narration.",
        estimated_seconds=30,
        research_sources=["source_001"],
    )

    script = Script(
        topic="Test Topic",
        target_duration_seconds=480,
        target_word_count=1100,
        hook="This is the hook.",
        sections=[section],
        total_estimated_seconds=30,
        total_word_count=5,
        closing_message="This is the conclusion.",
    )

    assert script.topic == "Test Topic"
    assert script.sections[0].section_id == "s1"


def test_script_section_duration_validation():
    with pytest.raises(ValueError):
        ScriptSection(
            section_id="s1",
            section_type="hook",
            title="Hook",
            narration="Test narration.",
            estimated_seconds=5,
        )


def test_script_requires_narration():
    with pytest.raises(ValueError):
        ScriptSection(
            section_id="s1",
            section_type="hook",
            title="Hook",
            narration="",
            estimated_seconds=30,
        )