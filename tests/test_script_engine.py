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
    NarrativeMovement,
    Script,
    ScriptHookPlan,
    ScriptQualityChecks,
    ScriptQualityFinding,
    ScriptQualityReview,
    ScriptSection,
    ScriptSectionRevision,
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


def _movement(section_id, *, reveal):
    return NarrativeMovement(
        section_id=section_id,
        purpose="Move the central mystery forward.",
        question="What does the evidence show?",
        evidence_source_ids=["source_001"],
        reveal=reveal,
        next_question="What new problem does that answer create?",
        visual_opportunity="Show the supported evidence as a clear human-scale scene.",
    )


def _quality_review(status, *, failed_check=None, findings=None):
    checks = {
        name: "PASS" for name in ScriptQualityChecks.model_fields
    }
    if failed_check:
        checks[failed_check] = "FAIL"
    return ScriptQualityReview(
        status=status,
        checks=ScriptQualityChecks(**checks),
        findings=findings or [],
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
        "Without central heating, what actually kept people alive through an "
        "ancient winter: clothing, shelter, fire, or food stores? The surprising "
        "answer lies in how these defenses worked together before the cold arrived."
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
            viewer_relevance=score,
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


def test_hook_quality_rejects_a_weak_hook_without_supported_replacement(tmp_path):
    script = create_script()

    def scores(text, score, factual_support, sources):
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
            viewer_relevance=score,
            factual_support=factual_support,
            source_ids=sources,
        )

    weak_review = HookQualityReview(
        current=scores(script.hook, 1, 2, ["source_001"]),
        alternatives=[
            scores(
                "A vivid but unsupported explanation promises a dramatic historical answer "
                "that would change everything we know about this mystery.",
                5,
                1,
                ["source_001"],
            )
        ],
    )

    class FakeResponses:
        def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed=weak_review)

    engine = ScriptEngine.__new__(ScriptEngine)
    engine.client = SimpleNamespace(responses=FakeResponses())

    with pytest.raises(ValueError, match="no fact-supported"):
        engine._review_and_strengthen_hook(
            script,
            create_research(),
            tmp_path,
        )

    report = json.loads((tmp_path / "hook_evaluation.json").read_text())
    assert report["status"] == "FAIL"
    assert report["iterations"][0]["alternatives"][0]["eligible"] is False


def test_script_quality_repair_revises_only_flagged_section(tmp_path):
    script = create_script()
    script = script.model_copy(
        update={
            "script_profile": "RITZZ_ANCIENT_HUMAN_CURIOSITY",
            "hook_plan": ScriptHookPlan(
                central_question="How did this work?",
                open_loop="The evidence suggests a less obvious answer.",
                stakes="The explanation changes how we see daily life.",
            ),
            "narrative_arc": [
                _movement("s1", reveal="The opening establishes a real puzzle."),
                _movement("s2", reveal="The closing supplies the supported answer."),
            ],
            "final_payoff": "The conclusion resolves the opening mystery.",
            "viewer_connection": "The same question matters to modern viewers.",
        }
    )
    finding = ScriptQualityFinding(
        category="WEAK_EVIDENCE",
        section_ids=["s2"],
        rationale="The closing states a conclusion without grounding it.",
        revision_instruction="Tie the closing answer to the supplied source evidence.",
        research_source_ids=["source_001"],
    )
    revised_movement = _movement(
        "s2",
        reveal="The cited evidence supports a qualified answer.",
    )
    responses = [
        _quality_review("FAIL", failed_check="evidence_integration", findings=[finding]),
        ScriptSectionRevision(
            section_id="s2",
            narration="This is the final narration, now tied to the supported evidence.",
            movement=revised_movement,
            viewer_connection="A modern viewer can recognize the same underlying problem.",
        ),
        _quality_review("PASS"),
    ]

    class FakeResponses:
        def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed=responses.pop(0))

    engine = ScriptEngine.__new__(ScriptEngine)
    engine.client = SimpleNamespace(responses=FakeResponses())
    original_hook_narration = script.sections[0].narration
    script_directory = tmp_path / "project" / "script"
    script_directory.mkdir(parents=True)

    updated = engine._review_and_repair_narrative(
        script,
        create_research(),
        create_outline(),
        script_directory,
        ProductionConfig(target_duration_seconds=60, minimum_duration_seconds=60),
    )

    report = json.loads((script_directory / "script_quality_review.json").read_text())
    qa_report = json.loads(
        (script_directory.parent / "qa" / "qa_report.json").read_text()
    )
    assert updated.sections[0].narration == original_hook_narration
    assert updated.sections[1].narration.endswith("supported evidence.")
    assert updated.narrative_arc[1].reveal == revised_movement.reveal
    assert updated.viewer_connection.startswith("A modern viewer")
    assert report["status"] == "PASS"
    assert report["iterations"][0]["targeted_section_ids"] == ["s2"]
    assert [
        attempt["status"]
        for attempt in qa_report["stages"]["script_narrative_review"]
    ] == ["FAIL", "PASS"]


def test_targeted_script_revision_cannot_add_unapproved_evidence(tmp_path):
    script = create_script().model_copy(
        update={
            "script_profile": "RITZZ_ANCIENT_HUMAN_CURIOSITY",
            "hook_plan": ScriptHookPlan(
                central_question="What happened?",
                open_loop="The evidence leaves an important question.",
                stakes="The answer changes the interpretation.",
            ),
            "narrative_arc": [
                _movement("s1", reveal="An established puzzle."),
                _movement("s2", reveal="A supported conclusion."),
            ],
            "final_payoff": "The conclusion resolves the opening.",
        }
    )
    finding = ScriptQualityFinding(
        category="UNSUPPORTED_CLAIM",
        section_ids=["s2"],
        rationale="A claim in this section is not supported by the supplied research.",
        revision_instruction="Replace the unsupported claim with a sourced explanation.",
    )
    unsupported_movement = _movement(
        "s2",
        reveal="An unsupported explanation.",
    ).model_copy(update={"evidence_source_ids": ["invented_source"]})
    responses = [
        _quality_review("FAIL", failed_check="evidence_integration", findings=[finding]),
        ScriptSectionRevision(
            section_id="s2",
            narration="This revised conclusion introduces an unsupported claim.",
            movement=unsupported_movement,
        ),
    ]

    class FakeResponses:
        def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed=responses.pop(0))

    engine = ScriptEngine.__new__(ScriptEngine)
    engine.client = SimpleNamespace(responses=FakeResponses())
    script_directory = tmp_path / "project" / "script"
    script_directory.mkdir(parents=True)

    with pytest.raises(ValueError, match="outside its approved section sources"):
        engine._review_and_repair_narrative(
            script,
            create_research(),
            create_outline(),
            script_directory,
            ProductionConfig(
                target_duration_seconds=60,
                minimum_duration_seconds=60,
            ),
        )

    report = json.loads((script_directory / "script_quality_review.json").read_text())
    assert report["status"] == "FAIL"
    assert "unapproved research sources" in report["blocking_reason"]


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


def test_script_profile_and_duration_pacing_are_configurable():
    config = ProductionConfig(
        target_duration_seconds=120,
        minimum_duration_seconds=120,
        words_per_minute=120,
    )

    system_prompt = ScriptEngine._system_prompt(config)
    user_prompt = ScriptEngine._build_user_prompt(
        create_research(),
        create_outline(),
        config,
    )

    assert "RITZZ_ANCIENT_HUMAN_CURIOSITY" in system_prompt
    assert "one central mystery" in system_prompt
    assert "evidence" in user_prompt.lower()
    assert "Aim for about 240 spoken words" in system_prompt
    assert "240 spoken words (120 seconds)" in user_prompt
    assert ScriptEngine._calculate_duration_seconds(240, 120) == 120
    assert ScriptEngine._ten_second_hook_word_target(140) == 30


def test_script_input_fingerprint_tracks_profile_pacing_and_research():
    research = create_research()
    outline = create_outline()
    first_config = ProductionConfig(
        target_duration_seconds=120,
        minimum_duration_seconds=120,
        words_per_minute=120,
    )
    changed_pacing = first_config.model_copy(update={"words_per_minute": 130})

    original = ScriptEngine._script_input_fingerprint(
        research,
        outline,
        first_config,
    )
    assert original != ScriptEngine._script_input_fingerprint(
        research,
        outline,
        changed_pacing,
    )

    changed_research = research.model_copy(
        update={"short_answer": "A revised, independently supported answer."}
    )
    assert original != ScriptEngine._script_input_fingerprint(
        changed_research,
        outline,
        first_config,
    )


def test_narrative_metadata_requires_a_central_question_open_loop_and_payoff():
    script = create_script().model_copy(
        update={
            "script_profile": "RITZZ_ANCIENT_HUMAN_CURIOSITY",
            "narrative_arc": [
                _movement("s1", reveal="The opening establishes the mystery."),
                _movement("s2", reveal="The conclusion supplies an answer."),
            ],
            "final_payoff": "The conclusion resolves the opening question.",
        }
    )

    with pytest.raises(ValueError, match="hook plan and final payoff"):
        ScriptEngine._validate_narrative_metadata(
            script,
            create_research(),
            create_outline(),
            profile_id="RITZZ_ANCIENT_HUMAN_CURIOSITY",
        )


def test_script_validation_rejects_unknown_section_research_sources():
    script = create_script().model_copy(
        update={
            "sections": [
                create_script().sections[0].model_copy(
                    update={"research_sources": ["missing_source"]}
                ),
                create_script().sections[1],
            ]
        }
    )

    with pytest.raises(ValueError, match="unknown research source IDs"):
        ScriptEngine._validate_script(
            script,
            create_research(),
            create_outline(),
            minimum_word_count=1,
            minimum_duration_seconds=1,
        )


def test_profiled_script_validation_rejects_a_short_opening_hook():
    script = create_script()
    short_hook = "A short hook."
    script = script.model_copy(
        update={
            "hook": short_hook,
            "script_profile": "RITZZ_ANCIENT_HUMAN_CURIOSITY",
            "sections": [
                script.sections[0].model_copy(
                    update={"narration": f"{short_hook} Continue the story."}
                ),
                script.sections[1],
            ],
        }
    )

    with pytest.raises(ValueError, match="roughly 10-second opening"):
        ScriptEngine._validate_script(
            script,
            create_research(),
            create_outline(),
            minimum_word_count=1,
            minimum_duration_seconds=1,
            maximum_duration_seconds=600,
        )


def test_script_validation_enforces_configured_maximum_duration():
    script = create_script()
    actual_duration = ScriptEngine._calculate_duration_seconds(
        ScriptEngine._calculate_word_count(script),
        words_per_minute=120,
    )
    script = script.model_copy(
        update={"total_estimated_seconds": actual_duration}
    )

    with pytest.raises(ValueError, match="maximum acceptable duration"):
        ScriptEngine._validate_script(
            script,
            create_research(),
            create_outline(),
            minimum_word_count=1,
            minimum_duration_seconds=1,
            words_per_minute=120,
            maximum_duration_seconds=actual_duration - 1,
        )


def test_script_prompts_require_a_ten_second_spoken_hook():
    prompt = ScriptEngine._build_user_prompt(
        create_research(),
        create_outline(),
    )

    assert "about 30 spoken words (roughly 10 seconds)" in prompt
    assert "first spoken words of the first hook section" in prompt
    assert "Script.hook field must match this opening text" in prompt
    assert "do not repeat the hook later" in prompt


def test_ten_second_hook_target_scales_and_stays_within_validation_range():
    assert ScriptEngine._ten_second_hook_word_target(80) == 17
    assert ScriptEngine._ten_second_hook_word_target(140) == 30
    assert ScriptEngine._ten_second_hook_word_target(220) == 38


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

    assert "opening hook of about 30 words" in expansion_prompt
    assert "opening hook of about 30 words" in contraction_prompt
