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


def _qualified_hook_candidate(**updates):
    values = {
        "text": (
            "People once faced this challenge without the tools we now take for "
            "granted. The clues they left behind do not point to an obvious answer. "
            "How did they solve the problem? The evidence can reveal the choices "
            "available to them, but the mechanism is not as simple as it first "
            "appears. Follow the sources and we can separate documented possibilities "
            "from assumptions."
        ),
        "modern_connection_applicable": False,
        "ancient_problem": "People in the past faced the same basic human challenge.",
        "curiosity_question": "How did they solve the problem?",
        "open_loop_description": "The available evidence does not settle the mechanism.",
        "stakes_description": "The answer changes how the evidence is interpreted.",
        "visual_opportunity": "Show people confronting the problem and the evidence left behind.",
        "first_investigation": "The opening section begins comparing the available evidence.",
        "curiosity_mechanism": "EVIDENCE_LED_MYSTERY",
        "curiosity": 5,
        "tension": 5,
        "specificity": 5,
        "stakes": 5,
        "novelty": 5,
        "clarity": 5,
        "open_loop": 5,
        "payoff_promise": 5,
        "viewer_relevance": 5,
        "factual_support": 5,
        "source_ids": ["source_001"],
        "modern_relevance": 5,
        "problem_clarity": 5,
        "ancient_connection": 5,
        "surprise": 5,
        "conversational_quality": 5,
        "visual_potential": 5,
        "story_continuity": 5,
    }
    values.update(updates)
    return HookCandidateScores(**values)


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
        "Today, a familiar task feels easy because modern tools hide the hard part. "
        "But people in the ancient world faced the same underlying problem without "
        "those tools. How did they make it work? The surviving evidence offers clues, "
        "but not one universal answer. By comparing what sources actually show, we "
        "can uncover the choices and constraints behind a solution that is easy to "
        "overlook now."
    )
    alternatives = [
        (
            (
                "Picture an ordinary modern moment when a device solves an annoying "
                "problem before you even think about it. Now remove that convenience and "
                "place the same challenge in an ancient setting. What could people do "
                "instead? The answer is not a single trick; it depends on what they had, "
                "what the evidence records, and which risks mattered most. That is the "
                "puzzle we can test."
            ),
            "EVERYDAY_CONVENIENCE",
            "What could people do instead?",
        ),
        (
            (
                "We assume the simplest way to handle a daily problem has always been "
                "obvious. It has not. Before the familiar modern fix existed, people "
                "still faced the same basic challenge. Which choices helped them cope, "
                "and what can the surviving evidence really prove? The most interesting "
                "clue may not be the one we expect, so let's separate documented methods "
                "from later assumptions."
            ),
            "ASSUMPTION_REVERSAL",
            "Which choices helped them cope, and what can the surviving evidence really prove?",
        ),
        (
            (
                "A modern shortcut can make a difficult job feel almost automatic. "
                "Remove that shortcut, and the same human need becomes a very different "
                "puzzle. People in the ancient world still had to face it, but the traces "
                "they left behind are incomplete. What do those traces let us say with "
                "confidence, and what remains uncertain? The answer starts with the "
                "problem, not a dramatic guess."
            ),
            "EVIDENCE_MYSTERY",
            "What do those traces let us say with confidence, and what remains uncertain?",
        ),
    ]

    def scores(
        text: str,
        score: int,
        factual_support: int,
        sources: list[str],
        mechanism: str,
        question: str,
    ):
        return HookCandidateScores(
            text=text,
            modern_connection_applicable=True,
            modern_situation="A familiar task feels easy with modern tools.",
            modern_solution="Modern tools hide the difficult part.",
            shared_problem="The same underlying human challenge.",
            ancient_problem="People faced the same challenge in the ancient world.",
            curiosity_question=question,
            open_loop_description="The evidence offers clues without resolving every detail.",
            stakes_description="The problem affected ordinary choices.",
            visual_opportunity="Contrast a modern tool with an ancient person facing the same task.",
            first_investigation="The opening section immediately examines evidence about that problem.",
            curiosity_mechanism=mechanism,
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
            modern_relevance=score,
            problem_clarity=score,
            ancient_connection=score,
            surprise=score,
            conversational_quality=score,
            visual_potential=score,
            story_continuity=score,
        )

    review = HookQualityReview(
        current=scores(
            old_hook,
            2,
            4,
            ["source_001"],
            "GENERIC_OPENING",
            "How did they make it work?",
        ),
        alternatives=[
            scores(text, 5, 5, ["source_001"], mechanism, question)
            for text, mechanism, question in [
                (
                    candidate_text,
                    "MODERN_CONTRAST",
                    "How did they make it work?",
                ),
                *alternatives,
            ]
        ],
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
    assert ScriptEngine._distinct_hook_candidates(
        review.alternatives
    )
    assert updated.hook == candidate_text
    assert updated.sections[0].narration.startswith(candidate_text)
    assert updated.sections[1] == script.sections[1]
    assert report["status"] == "PASS"
    assert report["regenerated"] is True
    assert report["iterations"][0]["alternatives"][0]["eligible"] is True
    assert report["version"] == 3
    assert report["selected_score"] >= 4
    assert updated.hook_plan.modern_connection_applicable is True
    assert updated.hook_plan.ancient_problem
    assert updated.hook_plan.curiosity_question in updated.hook
    assert updated.hook_plan.source_ids == ["source_001"]
    assert (tmp_path / "script.json").is_file()


def test_hook_quality_rejects_a_weak_hook_without_supported_replacement(tmp_path):
    script = create_script()

    alternatives = [
        (
            "A vivid unsupported claim could transform the entire story, but the sources "
            "do not establish what happened. What hidden force changed everything? The "
            "evidence cannot answer that question, and this dramatic possibility rests "
            "on speculation rather than documented findings."
        ),
        (
            "An astonishing explanation may rewrite the past, if a secret event occurred. "
            "What powerful discovery did people conceal? No approved source supports this "
            "claim, so the exciting answer would be invented rather than researched."
        ),
        (
            "Imagine a shocking twist that changes every historical account. Could an "
            "unknown invention explain the mystery? The available research gives no basis "
            "for that claim, and presenting it as true would mislead the viewer."
        ),
    ]

    def scores(text, score, factual_support, sources, mechanism, question):
        return HookCandidateScores(
            text=text,
            modern_connection_applicable=False,
            ancient_problem="The historical question described in the supplied research.",
            curiosity_question=question,
            open_loop_description="The evidence leaves the historical explanation unresolved.",
            stakes_description="The evidence matters to the interpretation.",
            visual_opportunity="Show the historical evidence being examined.",
            first_investigation="The opening section starts testing the historical evidence.",
            curiosity_mechanism=mechanism,
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
            modern_relevance=score,
            problem_clarity=score,
            ancient_connection=score,
            surprise=score,
            conversational_quality=score,
            visual_potential=score,
            story_continuity=score,
        )

    weak_review = HookQualityReview(
        current=scores(
            script.hook,
            1,
            2,
            ["source_001"],
            "GENERIC",
            "What happened?",
        ),
        alternatives=[
            scores(
                text,
                5,
                1,
                ["source_001"],
                mechanism,
                question,
            )
            for text, mechanism, question in zip(
                alternatives,
                ["SECRET_TWIST", "HIDDEN_DISCOVERY", "SHOCKING_EXPLANATION"],
                [
                    "What hidden force changed everything?",
                    "What powerful discovery did people conceal?",
                    "Could an unknown invention explain the mystery?",
                ],
                strict=True,
            )
        ],
    )

    class FakeResponses:
        def parse(self, **_kwargs):
            return SimpleNamespace(output_parsed=weak_review)

    engine = ScriptEngine.__new__(ScriptEngine)
    engine.client = SimpleNamespace(responses=FakeResponses())

    with pytest.raises(ValueError, match="factual-support"):
        engine._review_and_strengthen_hook(
            script,
            create_research(),
            tmp_path,
        )

    report = json.loads((tmp_path / "hook_evaluation.json").read_text())
    assert report["status"] == "FAIL"
    assert report["iterations"][0]["alternatives"][0]["eligible"] is False


def test_hook_gate_does_not_force_a_modern_comparison_for_topic_specific_hooks():
    candidate = _qualified_hook_candidate()

    assert ScriptEngine._hook_meets_retention_gate(
        candidate,
        47,
        81,
        {"source_001"},
    )


def test_hook_gate_requires_a_supported_modern_to_ancient_bridge_when_applicable():
    candidate = _qualified_hook_candidate(
        modern_connection_applicable=True,
        modern_situation="A modern person solves the problem with a familiar tool.",
        modern_solution="The tool makes the task convenient.",
        shared_problem="The same underlying human problem.",
        modern_relevance=5,
        problem_clarity=5,
        ancient_connection=5,
    )
    assert ScriptEngine._hook_meets_retention_gate(
        candidate,
        47,
        81,
        {"source_001"},
    )

    unsupported_bridge = candidate.model_copy(
        update={
            "shared_problem": "",
            "ancient_connection": 2,
        }
    )
    assert not ScriptEngine._hook_meets_retention_gate(
        unsupported_bridge,
        47,
        81,
        {"source_001"},
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"open_loop": 2},
        {"factual_support": 2},
        {"source_ids": ["unapproved_source"]},
        {"curiosity_question": "What did people do?", "text": "A hook with a late question. " + _qualified_hook_candidate().text.replace("How did they solve the problem?", "") + " What did people do?"},
    ],
)
def test_hook_gate_rejects_missing_curiosity_or_research_support(updates):
    assert not ScriptEngine._hook_meets_retention_gate(
        _qualified_hook_candidate(**updates),
        47,
        81,
        {"source_001"},
    )


def test_hook_candidates_must_use_distinct_mechanisms_and_wording():
    first = _qualified_hook_candidate(curiosity_mechanism="EVERYDAY_PROBLEM")
    second = _qualified_hook_candidate(curiosity_mechanism="MODERN_CONTRAST")
    third = _qualified_hook_candidate(curiosity_mechanism="IMPOSSIBILITY")

    assert not ScriptEngine._distinct_hook_candidates([first, second, third])
    distinct = [
        first,
        second.model_copy(
            update={
                "text": (
                    "Before familiar modern tools, a routine task could demand "
                    "careful choices. People in the ancient world met the same "
                    "fundamental challenge with different limits. What options did "
                    "they have? The records are incomplete, so no single answer fits "
                    "every place. By following the evidence, we can see how their "
                    "decisions shaped what happened next."
                )
            }
        ),
        third.model_copy(
            update={
                "text": (
                    "A simple modern fix can make a difficult problem disappear "
                    "from view. Long before it existed, people still had to deal "
                    "with the same need. Could they manage without it? The evidence "
                    "is more complicated than a clever invention or one dramatic "
                    "trick. Looking closely at what survived reveals which answers "
                    "are possible and which remain uncertain."
                ),
                "curiosity_question": "Could they manage without it?",
            }
        ),
    ]
    assert ScriptEngine._distinct_hook_candidates(distinct)


def test_hook_quality_score_uses_configurable_dimension_weights():
    candidate = _qualified_hook_candidate(open_loop=1, curiosity=5)

    curiosity_weighted = ScriptEngine._hook_candidate_score(
        candidate,
        {"curiosity": 1.0},
    )
    loop_weighted = ScriptEngine._hook_candidate_score(
        candidate,
        {"open_loop": 1.0},
    )

    assert curiosity_weighted == 5
    assert loop_weighted == 1
    assert ScriptEngine._hook_candidate_score(
        _qualified_hook_candidate(modern_relevance=0),
        ProductionConfig().hook_quality_weights,
    ) == pytest.approx(5)


def test_hook_candidate_metadata_is_persisted_and_validated():
    candidate = _qualified_hook_candidate(
        modern_connection_applicable=True,
        modern_situation="A modern person solves the problem with a familiar tool.",
        modern_solution="The tool makes the task convenient.",
        shared_problem="The same underlying human problem.",
    )
    script = create_script()
    script = script.model_copy(
        update={
            "sections": [
                script.sections[0].model_copy(
                    update={
                        "narration": (
                            f"{script.hook} The first section investigates that same "
                            "question using the available evidence."
                        )
                    }
                ),
                *script.sections[1:],
            ]
        }
    )
    updated = ScriptEngine._apply_hook_candidate(
        script,
        candidate,
        score=4.75,
        words_per_minute=140,
    )

    ScriptEngine._validate_hook_metadata(updated, create_research())
    assert updated.hook_plan.modern_situation == candidate.modern_situation
    assert updated.hook_plan.modern_solution == candidate.modern_solution
    assert updated.hook_plan.shared_problem == candidate.shared_problem
    assert updated.hook_plan.quality_score == 4.75
    assert updated.hook_plan.source_ids == ["source_001"]

    mismatched = updated.model_copy(
        update={
            "hook_plan": updated.hook_plan.model_copy(
                update={"curiosity_question": "What happened instead?"}
            )
        }
    )
    with pytest.raises(ValueError, match="does not appear in the spoken opening"):
        ScriptEngine._validate_hook_metadata(mismatched, create_research())


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


def test_system_prompt_bans_generic_suspense_filler_and_shows_the_required_shift():
    system_prompt = ScriptEngine._system_prompt()
    for phrase in ScriptEngine.BANNED_NARRATION_FILLER_PHRASES:
        assert phrase in system_prompt
    assert "generic suspense filler" in system_prompt
    assert "Weak pattern to avoid" in system_prompt
    assert "Apply this shift throughout every section" in system_prompt


def test_hook_evaluator_prompt_bans_generic_suspense_filler(tmp_path):
    captured: dict = {}
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
        "Today, a familiar task feels easy because modern tools hide the hard part. "
        "But people in the ancient world faced the same underlying problem without "
        "those tools. How did they make it work? The surviving evidence offers clues, "
        "but not one universal answer. By comparing what sources actually show, we "
        "can uncover the choices and constraints behind a solution that is easy to "
        "overlook now."
    )

    def scores(text, score, factual_support, sources, mechanism, question):
        return HookCandidateScores(
            text=text,
            modern_connection_applicable=True,
            modern_situation="A familiar task feels easy with modern tools.",
            modern_solution="Modern tools hide the difficult part.",
            shared_problem="The same underlying human challenge.",
            ancient_problem="People faced the same challenge in the ancient world.",
            curiosity_question=question,
            open_loop_description="The evidence offers clues without resolving every detail.",
            stakes_description="The problem affected ordinary choices.",
            visual_opportunity="Contrast a modern tool with an ancient person facing the same task.",
            first_investigation="The opening section immediately examines evidence about that problem.",
            curiosity_mechanism=mechanism,
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
            modern_relevance=score,
            problem_clarity=score,
            ancient_connection=score,
            surprise=score,
            conversational_quality=score,
            visual_potential=score,
            story_continuity=score,
        )

    other_candidates = [
        (
            (
                "Picture an ordinary modern moment when a device solves an annoying "
                "problem before you even think about it. Now remove that convenience and "
                "place the same challenge in an ancient setting. What could people do "
                "instead? The answer is not a single trick; it depends on what they had, "
                "what the evidence records, and which risks mattered most. That is the "
                "puzzle we can test."
            ),
            "EVERYDAY_CONVENIENCE",
            "What could people do instead?",
        ),
        (
            (
                "We assume the simplest way to handle a daily problem has always been "
                "obvious. It has not. Before the familiar modern fix existed, people "
                "still faced the same basic challenge. Which choices helped them cope, "
                "and what can the surviving evidence really prove? The most interesting "
                "clue may not be the one we expect, so let's separate documented methods "
                "from later assumptions."
            ),
            "ASSUMPTION_REVERSAL",
            "Which choices helped them cope, and what can the surviving evidence really prove?",
        ),
    ]
    review = HookQualityReview(
        current=scores(old_hook, 2, 4, ["source_001"], "GENERIC_OPENING", "How?"),
        alternatives=[
            scores(candidate_text, 5, 5, ["source_001"], "MODERN_CONTRAST", "How did they make it work?"),
            *(
                scores(text, 5, 5, ["source_001"], mechanism, question)
                for text, mechanism, question in other_candidates
            ),
        ],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            captured["input"] = kwargs["input"]
            return SimpleNamespace(output_parsed=review)

    engine = ScriptEngine.__new__(ScriptEngine)
    engine.client = SimpleNamespace(responses=FakeResponses())

    engine._review_and_strengthen_hook(
        script,
        create_research(),
        tmp_path,
    )

    system_message = next(
        message["content"]
        for message in captured["input"]
        if message["role"] == "system"
    )
    for phrase in ScriptEngine.BANNED_NARRATION_FILLER_PHRASES:
        assert phrase in system_message
    assert "WEAK_CURIOSITY" in system_message


def test_narrative_reviewer_prompt_flags_generic_suspense_filler(tmp_path):
    captured: dict = {}
    script = create_script().model_copy(
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
    passing_review = _quality_review("PASS")

    class FakeResponses:
        def parse(self, **kwargs):
            captured["input"] = kwargs["input"]
            return SimpleNamespace(output_parsed=passing_review)

    engine = ScriptEngine.__new__(ScriptEngine)
    engine.client = SimpleNamespace(responses=FakeResponses())
    script_directory = tmp_path / "project" / "script"
    script_directory.mkdir(parents=True)

    engine._review_and_repair_narrative(
        script,
        create_research(),
        create_outline(),
        script_directory,
        ProductionConfig(),
    )

    system_message = next(
        message["content"]
        for message in captured["input"]
        if message["role"] == "system"
    )
    for phrase in ScriptEngine.BANNED_NARRATION_FILLER_PHRASES:
        assert phrase in system_message
    assert "generic suspense filler" in system_message


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
    assert ScriptEngine._hook_word_bounds(140) == (47, 81)


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

    with pytest.raises(ValueError, match="20–35-second opening"):
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


def test_script_prompts_require_a_twenty_to_thirty_five_second_spoken_hook():
    prompt = ScriptEngine._build_user_prompt(
        create_research(),
        create_outline(),
    )

    assert "about 20–35 seconds" in prompt
    assert "modern problem" in prompt
    assert "Do not force an artificial modern comparison" in ScriptEngine._system_prompt()
    assert "first spoken words of the first hook section" in prompt
    assert "Keep Script.hook exactly equal to this opening" in prompt
    assert "do not repeat it later" in prompt


def test_hook_word_bounds_scale_to_twenty_thirty_five_seconds():
    assert ScriptEngine._hook_word_bounds(80) == (27, 46)
    assert ScriptEngine._hook_word_bounds(140) == (47, 81)
    assert ScriptEngine._hook_word_bounds(220) == (74, 128)


def test_script_retry_prompts_preserve_the_twenty_to_thirty_five_second_hook():
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

    assert "opening hook of 47–81 words (about 20–35 seconds)" in expansion_prompt
    assert "opening hook of 47–81 words (about 20–35 seconds)" in contraction_prompt
