import json
from types import SimpleNamespace

from modules.outline.engine import OutlineEngine
from modules.outline.models import Outline, OutlineSection
from modules.project.config import ProductionConfig
from modules.research.models import Research


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


def test_outline_prompt_includes_accepted_duration_range():
    config = ProductionConfig(
        target_duration_seconds=120,
        minimum_duration_seconds=120,
    )
    system_prompt = OutlineEngine._system_prompt(config)
    user_prompt = OutlineEngine._build_user_prompt(
        Research(
            topic="Test topic",
            category="Education",
            core_question="What is the answer?",
            short_answer="A short answer.",
        ),
        config,
    )

    assert "between 120 and 180 seconds" in system_prompt
    assert "TARGET DURATION: approximately 120 seconds." in user_prompt
    assert "between 120 and 180 seconds" in user_prompt
    assert "estimated_seconds values for all sections MUST sum" in user_prompt


def test_invalid_cached_outline_is_regenerated_with_qa_feedback(tmp_path):
    research = Research(
        topic="Test topic",
        category="Education",
        core_question="What is the answer?",
        short_answer="A short answer.",
    )
    research_file = tmp_path / "research.json"
    research_file.write_text(research.model_dump_json(), encoding="utf-8")
    outline_directory = tmp_path / "outline"
    outline_directory.mkdir()
    outline_file = outline_directory / "outline.json"
    invalid_cached = Outline(
        topic="Test topic",
        target_duration_seconds=120,
        hook="Hook",
        sections=[
            OutlineSection(
                section_id="section_001",
                section_type="hook",
                title="Hook",
                purpose="Create curiosity.",
                estimated_seconds=90,
            )
        ],
        total_estimated_seconds=90,
        closing_message="Conclusion",
    )
    outline_file.write_text(invalid_cached.model_dump_json(), encoding="utf-8")
    valid = invalid_cached.model_copy(
        update={
            "sections": [
                invalid_cached.sections[0].model_copy(
                    update={"estimated_seconds": 140}
                )
            ],
            "total_estimated_seconds": 140,
        }
    )
    prompts = []

    class Responses:
        def parse(self, **kwargs):
            prompts.append(kwargs["input"][1]["content"])
            return SimpleNamespace(output_parsed=valid)

    engine = OutlineEngine.__new__(OutlineEngine)
    engine.client = SimpleNamespace(responses=Responses())

    result = engine.create_outline(
        research_file,
        outline_directory,
        production_config=ProductionConfig(
            target_duration_seconds=120,
            minimum_duration_seconds=120,
        ),
    )

    assert result.total_estimated_seconds == 140
    assert len(prompts) == 1
    assert "Cached outline failed QA" in prompts[0]
    assert "90s" in prompts[0]


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


def test_outline_accepts_small_reported_duration_difference_and_normalizes_total():
    outline = Outline(
        topic="Test Topic",
        target_duration_seconds=180,
        hook="Hook",
        sections=[
            OutlineSection(
                section_id="section_001",
                section_type="hook",
                title="Hook",
                purpose="Create curiosity.",
                estimated_seconds=102,
            ),
            OutlineSection(
                section_id="section_002",
                section_type="explanation",
                title="Explanation",
                purpose="Explain the topic.",
                estimated_seconds=80,
            ),
        ],
        total_estimated_seconds=180,
        closing_message="Conclusion",
    )

    validated = OutlineEngine._validate_duration(
        outline,
        target_duration_seconds=180,
        minimum_duration_seconds=180,
    )

    assert validated.total_estimated_seconds == 182
    assert validated.target_duration_seconds == 180


def test_generated_outline_with_two_second_rounding_difference_is_saved(tmp_path):
    outline = Outline(
        topic="Test Topic",
        target_duration_seconds=180,
        hook="Hook",
        sections=[
            OutlineSection(
                section_id="section_001",
                section_type="hook",
                title="Hook",
                purpose="Create curiosity.",
                estimated_seconds=102,
            ),
            OutlineSection(
                section_id="section_002",
                section_type="explanation",
                title="Explanation",
                purpose="Explain the topic.",
                estimated_seconds=80,
            ),
        ],
        total_estimated_seconds=180,
        closing_message="Conclusion",
    )
    engine = OutlineEngine.__new__(OutlineEngine)
    engine.client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=lambda **kwargs: SimpleNamespace(output_parsed=outline)
        )
    )
    research_file = tmp_path / "research.json"
    research_file.write_text(
        Research(
            topic="Test Topic",
            category="History",
            core_question="How did it work?",
            short_answer="It worked this way.",
        ).model_dump_json(),
        encoding="utf-8",
    )

    result = engine.create_outline(
        research_file,
        tmp_path / "outline",
        force_refresh=True,
        production_config=ProductionConfig(
            target_duration_seconds=180,
            minimum_duration_seconds=180,
        ),
    )

    saved = json.loads(
        (tmp_path / "outline" / "outline.json").read_text(encoding="utf-8")
    )
    assert result.total_estimated_seconds == 182
    assert saved["total_estimated_seconds"] == 182


def test_outline_duration_enforces_minimum_and_sixty_second_upper_tolerance():
    outline = Outline(
        topic="Test Topic",
        target_duration_seconds=180,
        hook="Hook",
        sections=[
            OutlineSection(
                section_id="section_001",
                section_type="hook",
                title="Hook",
                purpose="Create curiosity.",
                estimated_seconds=179,
            ),
        ],
        total_estimated_seconds=179,
        closing_message="Conclusion",
    )

    try:
        OutlineEngine._validate_duration(
            outline,
            target_duration_seconds=180,
            minimum_duration_seconds=180,
        )
    except ValueError as exc:
        assert "acceptable range: 180-240s" in str(exc)
    else:
        raise AssertionError("Expected an outline below the configured minimum to fail")

    within_upper_tolerance = outline.model_copy(update={
        "sections": [
            outline.sections[0].model_copy(update={"estimated_seconds": 180}),
            outline.sections[0].model_copy(update={
                "section_id": "section_002",
                "section_type": "explanation",
                "estimated_seconds": 60,
            }),
        ],
        "total_estimated_seconds": 240,
    })
    OutlineEngine._validate_duration(
        within_upper_tolerance,
        target_duration_seconds=180,
        minimum_duration_seconds=180,
    )

    above_upper_tolerance = within_upper_tolerance.model_copy(update={
        "sections": [
            within_upper_tolerance.sections[0],
            within_upper_tolerance.sections[1].model_copy(
                update={"estimated_seconds": 61}
            ),
        ],
        "total_estimated_seconds": 241,
    })
    try:
        OutlineEngine._validate_duration(
            above_upper_tolerance,
            target_duration_seconds=180,
            minimum_duration_seconds=180,
        )
    except ValueError as exc:
        assert "acceptable range: 180-240s" in str(exc)
    else:
        raise AssertionError("Expected an outline over the configured upper tolerance to fail")


def test_outline_rejects_reported_total_difference_over_sixty_seconds():
    outline = Outline(
        topic="Test Topic",
        target_duration_seconds=180,
        hook="Hook",
        sections=[
            OutlineSection(
                section_id="section_001",
                section_type="hook",
                title="Hook",
                purpose="Create curiosity.",
                estimated_seconds=100,
            ),
        ],
        total_estimated_seconds=161,
        closing_message="Conclusion",
    )

    try:
        OutlineEngine._validate_duration(
            outline,
            target_duration_seconds=180,
            minimum_duration_seconds=180,
        )
    except ValueError as exc:
        assert "difference exceeds 60s" in str(exc)
    else:
        raise AssertionError("Expected a large reported-total mismatch to fail")


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