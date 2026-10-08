from types import SimpleNamespace

import pytest

from modules.research.models import Research, Source
from modules.storyboard.models import Storyboard, StoryboardScene
from modules.storyboard.visual_context import (
    SCENE_VISUAL_CONTRACTS_FILENAME,
    VISUAL_WORLD_BIBLE_FILENAME,
    VisualContextEngine,
    load_visual_world_bible,
)
from modules.storyboard.visual_models import (
    SceneVisualContract,
    SceneVisualContractBatch,
    VisualWorldBible,
)


def _scene(index: int) -> StoryboardScene:
    scene_id = f"scene_{index:03d}"
    return StoryboardScene(
        scene_id=scene_id,
        section_id="section_001",
        start_seconds=float(index),
        duration_seconds=3.0,
        narration=f"Scene narration {index}.",
        visual_description=f"A clear visual description for scene {index}.",
        image_prompt=f"A simple illustration for scene {index}.",
    )


def _contract(scene_id: str) -> SceneVisualContract:
    return SceneVisualContract(
        scene_id=scene_id,
        purpose="EXPLAIN",
        subject="A person",
        action="points at the object",
        environment="A simple room",
        historical_context="Not established by approved research.",
        ambiguity_resolution="Show the object literally.",
    )


def _world() -> VisualWorldBible:
    return VisualWorldBible(
        topic="Test Topic",
        historical=False,
        time_period="Not established by the approved research.",
        geography="Not established by the approved research.",
        civilization_or_society="Not established by the approved research.",
        technology_level="Contemporary everyday technology.",
        built_environment="Simple contemporary spaces.",
        clothing="Ordinary contemporary clothing.",
        transportation="Not relevant to this topic.",
        tools_and_weapons="Not established by the approved research.",
        containers_and_materials="Not established by the approved research.",
        architecture="Not established by the approved research.",
        natural_environment="Not established by the approved research.",
        social_context="Not established by the approved research.",
        visual_style="Simple hand-drawn 2D cartoon.",
        technology_ceiling="Contemporary everyday technology.",
    )


class _FakeResponses:
    def __init__(self, batches: list[SceneVisualContractBatch]) -> None:
        self.batches = iter(batches)
        self.formats: list[type] = []

    def parse(self, *, text_format: type, **_kwargs):
        self.formats.append(text_format)
        if text_format is VisualWorldBible:
            parsed = _world()
        else:
            parsed = next(self.batches)
        return SimpleNamespace(output_parsed=parsed)


def test_visual_context_plans_every_scene_in_order_and_persists_artifacts(tmp_path):
    scenes = [_scene(index) for index in range(1, 10)]
    storyboard = Storyboard(
        topic="Test Topic",
        target_duration_seconds=60,
        scenes=scenes,
        total_scene_duration_seconds=27.0,
    )
    research = Research(
        topic="Test Topic",
        category="Education",
        core_question="What is the topic?",
        short_answer="A concise answer.",
        sources=[
            Source(
                id="source_001",
                title="Evidence",
                url="https://example.com",
                publisher="Example",
                relevance="Supports the approved topic.",
                tier="1",
                source_type="reference",
            )
        ],
    )
    batches = [
        SceneVisualContractBatch(
            scenes=[_contract(scene.scene_id) for scene in scenes[:9]]
        ),
        SceneVisualContractBatch(scenes=[_contract(scenes[8].scene_id)]),
    ]
    responses = _FakeResponses(batches)
    engine = VisualContextEngine(
        client=SimpleNamespace(responses=responses),
        model="test-model",
    )

    updated, world, contracts = engine.plan(research, storyboard, tmp_path)

    assert [item.scene_id for item in contracts] == [
        scene.scene_id for scene in scenes
    ]
    assert all(scene.visual_contract is not None for scene in updated.scenes)
    assert responses.formats == [
        VisualWorldBible,
        SceneVisualContractBatch,
        SceneVisualContractBatch,
    ]
    assert load_visual_world_bible(tmp_path) == world
    assert (tmp_path / VISUAL_WORLD_BIBLE_FILENAME).is_file()
    assert (tmp_path / SCENE_VISUAL_CONTRACTS_FILENAME).is_file()


def test_visual_context_rejects_contracts_for_unrelated_scenes(tmp_path):
    scenes = [_scene(1), _scene(2)]
    storyboard = Storyboard(
        topic="Test Topic",
        target_duration_seconds=60,
        scenes=scenes,
        total_scene_duration_seconds=6.0,
    )
    research = Research(
        topic="Test Topic",
        category="Education",
        core_question="What is the topic?",
        short_answer="A concise answer.",
    )
    engine = VisualContextEngine(
        client=SimpleNamespace(
            responses=_FakeResponses(
                [
                    SceneVisualContractBatch(
                        scenes=[
                            _contract("scene_001"),
                            _contract("scene_002"),
                            _contract("scene_999"),
                        ]
                    )
                ]
            )
        ),
        model="test-model",
    )

    with pytest.raises(ValueError, match="outside the requested and adjacent scenes"):
        engine._plan_contracts(research, storyboard, _world())


def test_visual_context_rejects_topic_mismatch(tmp_path):
    research = Research(
        topic="Approved Topic",
        category="Education",
        core_question="Question?",
        short_answer="Answer.",
    )
    storyboard = Storyboard(
        topic="Different Topic",
        target_duration_seconds=60,
        scenes=[_scene(1)],
        total_scene_duration_seconds=3.0,
    )
    engine = VisualContextEngine(
        client=SimpleNamespace(responses=_FakeResponses([])),
        model="test-model",
    )

    with pytest.raises(ValueError, match="does not match approved research"):
        engine.plan(research, storyboard, tmp_path)
