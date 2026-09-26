import json

import pytest

from modules.outline.models import Outline, OutlineSection
from modules.project.config import ProductionConfig
from modules.research.models import (
    KeyFact,
    Research,
    Source,
)
from modules.script.engine import ScriptEngine
from modules.script.models import (
    Script,
    ScriptSection,
)


def create_research() -> Research:
    return Research(
        topic="Test Topic",
        category="Education",
        core_question="What is this about?",
        short_answer="This is the answer.",
        key_facts=[
            KeyFact(
                fact="Important fact.",
                importance="high",
                confidence="high",
                sources=["source_001"],
            )
        ],
        sources=[
            Source(
                id="source_001",
                title="Example Source",
                url="https://example.com",
                publisher="Example Publisher",
                relevance="Supports the main fact.",
                tier="1",
                source_type="reference",
            )
        ],
    )


def create_outline() -> Outline:
    return Outline(
        topic="Test Topic",
        target_duration_seconds=480,
        hook="This is the hook.",
        sections=[
            OutlineSection(
                section_id="s1",
                section_type="hook",
                title="The Hook",
                purpose="Create curiosity.",
                key_points=["Important fact."],
                estimated_seconds=30,
                research_sources=["source_001"],
            ),
            OutlineSection(
                section_id="s2",
                section_type="conclusion",
                title="The Conclusion",
                purpose="Wrap up the story.",
                key_points=["Final point."],
                estimated_seconds=30,
                research_sources=["source_001"],
            ),
        ],
        total_estimated_seconds=60,
        closing_message="That is the conclusion.",
    )


def create_script() -> Script:
    sections = [
        ScriptSection(
            section_id="s1",
            section_type="hook",
            title="The Hook",
            narration="This is the opening narration.",
            estimated_seconds=30,
            research_sources=["source_001"],
        ),
        ScriptSection(
            section_id="s2",
            section_type="conclusion",
            title="The Conclusion",
            narration="This is the final narration.",
            estimated_seconds=30,
            research_sources=["source_001"],
        ),
    ]

    word_count = sum(
        ScriptEngine._count_words(
            section.narration
        )
        for section in sections
    )

    return Script(
        topic="Test Topic",
        target_duration_seconds=60,
        target_word_count=1000,
        hook="This is the hook.",
        sections=sections,
        total_estimated_seconds=60,
        total_word_count=word_count,
        closing_message="That is the conclusion.",
    )


def test_load_research(tmp_path):
    research_file = tmp_path / "research.json"

    research = create_research()

    research_file.write_text(
        research.model_dump_json(indent=4),
        encoding="utf-8",
    )

    loaded = ScriptEngine._load_research(
        research_file
    )

    assert loaded.topic == "Test Topic"
    assert len(loaded.key_facts) == 1


def test_load_outline(tmp_path):
    outline_file = tmp_path / "outline.json"

    outline = create_outline()

    outline_file.write_text(
        outline.model_dump_json(indent=4),
        encoding="utf-8",
    )

    loaded = ScriptEngine._load_outline(
        outline_file
    )

    assert loaded.topic == "Test Topic"
    assert len(loaded.sections) == 2


def test_save_and_load_script(tmp_path):
    script_file = tmp_path / "script.json"

    script = create_script()

    ScriptEngine._save_script(
        script_file,
        script,
    )

    loaded = ScriptEngine._load_script(
        script_file
    )

    assert loaded.topic == "Test Topic"
    assert len(loaded.sections) == 2


def test_saved_script_contains_valid_json(tmp_path):
    script_file = tmp_path / "script.json"

    script = create_script()

    ScriptEngine._save_script(
        script_file,
        script,
    )

    data = json.loads(
        script_file.read_text(
            encoding="utf-8"
        )
    )

    assert isinstance(data, dict)
    assert data["topic"] == "Test Topic"


def test_script_duration_validation():
    script = create_script()

    broken_script = script.model_copy(
        update={
            "total_estimated_seconds": 120
        }
    )

    with pytest.raises(ValueError):
        ScriptEngine._validate_script(
            broken_script,
            create_research(),
            create_outline(),
        )


def test_script_validation_accepts_configured_short_duration():
    script = create_script().model_copy(
        update={"total_estimated_seconds": 4}
    )

    ScriptEngine._validate_script(
        script,
        create_research(),
        create_outline(),
        minimum_word_count=1,
        minimum_duration_seconds=1,
    )


def test_script_word_count_validation():
    script = create_script()

    broken_script = script.model_copy(
        update={
            "total_word_count": 999
        }
    )

    with pytest.raises(ValueError):
        ScriptEngine._validate_script(
            broken_script,
            create_research(),
            create_outline(),
        )


def test_script_topic_mismatch():
    script = create_script()

    broken_script = script.model_copy(
        update={
            "topic": "Different Topic"
        }
    )

    with pytest.raises(ValueError):
        ScriptEngine._validate_script(
            broken_script,
            create_research(),
            create_outline(),
        )


def test_word_count():
    text = "This is a simple test."

    count = ScriptEngine._count_words(text)

    assert count == 5


def test_script_generation_prompts_require_speech_friendly_punctuation():
    prompt = ScriptEngine._build_user_prompt(create_research(), create_outline())
    assert "Punctuate every narration section" in prompt
    assert "careful standard punctuation" in ScriptEngine._system_prompt()


def test_script_schema_allows_two_minute_target_word_count():
    script = create_script().model_copy(
        update={"target_word_count": 280}
    )
    serialized = script.model_dump_json()

    assert Script.model_validate_json(serialized).target_word_count == 280


def test_script_prompt_targets_configured_two_minute_length():
    from modules.project.config import ProductionConfig

    config = ProductionConfig(
        target_duration_seconds=120,
        minimum_duration_seconds=120,
    )
    prompt = ScriptEngine._system_prompt(config)

    assert "Aim for about 280 spoken words" in prompt
    assert "do not exceed 322 words" in prompt


def test_script_prompts_require_a_ten_second_spoken_hook():
    prompt = ScriptEngine._build_user_prompt(
        create_research(),
        create_outline(),
    )

    assert "about 25 spoken words (roughly 10 seconds)" in prompt
    assert "first spoken words of the first hook section" in prompt
    assert "Script.hook field must match this opening text" in prompt
    assert "do not repeat the hook later" in prompt


def test_script_retry_prompts_preserve_the_ten_second_hook():
    research = create_research()
    outline = create_outline()

    expansion_prompt = ScriptEngine._build_expansion_prompt(
        research,
        outline,
        current_word_count=100,
    )
    contraction_prompt = ScriptEngine._build_contraction_prompt(
        research,
        outline,
        current_word_count=900,
        config=ProductionConfig(),
    )

    assert "opening hook of about 25 words" in expansion_prompt
    assert "opening hook of about 25 words" in contraction_prompt
