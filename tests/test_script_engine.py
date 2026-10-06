import json
from types import SimpleNamespace

import pytest

from modules.outline.models import Outline, OutlineSection
from modules.project.config import ProductionConfig
from modules.research.models import (
    KeyFact,
    Research,
    Source,
)
from modules.script.engine import ScriptEngine
from modules.script.hook_quality import HookCandidateScores, HookQualityReview
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


def test_hook_replacement_changes_only_opening_text_and_recounts_script():
    script = create_script()
    old_hook = "A small change can reshape an entire world."
    new_hook = (
        "One unexpected clue reveals how a familiar object changed the course "
        "of history."
    )
    first_section = script.sections[0].model_copy(
        update={
            "narration": (
                f"{old_hook} The next sentence explains the larger mystery."
            )
        }
    )
    script = script.model_copy(
        update={
            "hook": old_hook,
            "sections": [first_section, *script.sections[1:]],
        }
    )

    updated = ScriptEngine._replace_opening_hook(script, new_hook)

    assert updated.hook == new_hook
    assert updated.sections[0].narration == (
        f"{new_hook} The next sentence explains the larger mystery."
    )
    assert updated.sections[1] == script.sections[1]
    assert updated.total_word_count == ScriptEngine._calculate_word_count(updated)
    assert updated.total_estimated_seconds == ScriptEngine._calculate_duration_seconds(
        updated.total_word_count
    )


def test_hook_evaluation_selects_supported_candidate_and_writes_report(
    tmp_path,
    monkeypatch,
):
    script = create_script()
    old_hook = (
        "This is a weak opening hook with very little curiosity or specificity."
    )
    first_section = script.sections[0].model_copy(
        update={"narration": f"{old_hook} The remaining spoken section continues."}
    )
    script = script.model_copy(
        update={"hook": old_hook, "sections": [first_section, *script.sections[1:]]}
    )
    candidate_text = (
        "One unexpected clue reveals how a familiar object changed the course "
        "of history."
    )

    def scores(text: str, score: int, factual_support: int, sources: list[str]):
        return HookCandidateScores(
            text=text,
            curiosity=score,
            tension=score,
            specificity=score,
            stakes=score,
            novelty=score,
            clarity=score,
            open_loop=score,
            payoff_promise=score,
            factual_support=factual_support,
            source_ids=sources,
        )

    review = HookQualityReview(
        current=scores(old_hook, 2, 4, ["source_001"]),
        alternatives=[scores(candidate_text, 5, 5, ["source_001"])],
    )

    class FakeResponses:
        def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed=review)

    engine = ScriptEngine.__new__(ScriptEngine)
    engine.client = SimpleNamespace(responses=FakeResponses())
    monkeypatch.setenv("RITZZ_HOOK_MIN_SCORE", "3.5")

    updated = engine._review_and_strengthen_hook(
        script,
        create_research(),
        tmp_path,
    )

    report = json.loads((tmp_path / "hook_evaluation.json").read_text())
    assert updated.hook == candidate_text
    assert updated.sections[0].narration.startswith(candidate_text)
    assert report["status"] == "PASS"
    assert report["regenerated"] is True
    assert report["iterations"][0]["alternatives"][0]["eligible"] is True
    assert (tmp_path / "script.json").is_file()


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
    user_prompt = ScriptEngine._build_user_prompt(
        create_research(),
        create_outline(),
        config,
    )

    assert "Aim for about 280 spoken words" in prompt
    assert "do not exceed 420 words" in prompt
    assert "420 words (180 seconds)" in user_prompt


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
