from pathlib import Path

import pytest

from modules.image.batch import ImageBatchEngine
from modules.image.engine import ImageEngine
from modules.image.models import ImageAsset
from modules.image.prompt_builder import ImagePromptBuilder
from modules.image.providers.mock import MockImageProvider
from modules.storyboard.models import Storyboard, StoryboardScene


def create_test_storyboard() -> Storyboard:
    scenes = [
        StoryboardScene(
            scene_id="scene_001",
            section_id="section_001",
            start_seconds=0.0,
            duration_seconds=5.0,
            narration="A pirate stands on a wooden ship.",
            visual_style="stickman",
            visual_description=(
                "A pirate standing on a wooden ship."
            ),
            character_action=(
                "The pirate looks toward the viewer."
            ),
            background=(
                "Wooden pirate ship deck."
            ),
            props=[
                "eye patch",
                "ship wheel",
            ],
            text_overlay="Why the eye patch?",
            camera_motion="static",
            transition="cut",
            research_sources=[
                "https://example.com/source"
            ],
            image_prompt="Pirate standing on a ship.",
        ),
        StoryboardScene(
            scene_id="scene_002",
            section_id="section_001",
            start_seconds=5.0,
            duration_seconds=5.0,
            narration="The pirate points toward the horizon.",
            visual_style="stickman",
            visual_description=(
                "A pirate pointing toward the ocean horizon."
            ),
            character_action=(
                "The pirate raises one arm toward the horizon."
            ),
            background=(
                "Simple ocean and sky."
            ),
            props=[
                "ship wheel",
            ],
            text_overlay="",
            camera_motion="slow_zoom_in",
            transition="cut",
            research_sources=[
                "https://example.com/source"
            ],
            image_prompt="Pirate pointing toward horizon.",
        ),
    ]

    return Storyboard(
        topic="Why Do Pirates Wear Eye Patches?",
        target_duration_seconds=10,
        scenes=scenes,
        total_scene_duration_seconds=10.0,
        target_scene_duration_seconds=5.0,
    )


def test_create_requests_returns_one_request_per_scene(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    requests = batch_engine.create_requests(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    assert len(requests) == 2


def test_create_requests_preserves_scene_ids(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    requests = batch_engine.create_requests(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    assert requests[0].image_id == "scene_001"
    assert requests[0].scene_id == "scene_001"

    assert requests[1].image_id == "scene_002"
    assert requests[1].scene_id == "scene_002"


def test_create_requests_uses_output_directory(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    requests = batch_engine.create_requests(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    for request in requests:
        assert request.output_directory == str(tmp_path)


def test_create_requests_uses_1536x864(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    requests = batch_engine.create_requests(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    for request in requests:
        assert request.width == 1536
        assert request.height == 864


def test_prompts_use_prompt_builder(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    requests = batch_engine.create_requests(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    prompt = requests[0].prompt

    # Ritzz global visual style.
    assert "Simple 2D cartoon illustration" in prompt
    assert "thick black outlines" in prompt
    assert "flat colors" in prompt
    assert "very minimal shading" in prompt
    assert "YouTube explainer animation style" in prompt

    # Landscape output.
    assert "Landscape 16:9 composition." in prompt

    # Scene-specific content.
    assert (
        "Scene: A pirate standing on a wooden ship."
        in prompt
    )

    assert (
        "Action: The pirate looks toward the viewer."
        in prompt
    )

    assert (
        "Background: Wooden pirate ship deck."
        in prompt
    )

    assert (
        "Props: eye patch, ship wheel"
        in prompt
    )

    # Editorial text embedded in the generated illustration.
    assert (
        'Editorial text inside the illustration: '
        '"Why the eye patch?".'
        in prompt
    )

    assert (
        "short, large, bold, readable"
        in prompt
    )

    assert (
        "naturally integrated into the composition"
        in prompt
    )

    assert (
        "not a subtitle or caption"
        in prompt
    )

    # Camera instruction.
    assert "Static camera." in prompt


def test_prompt_without_editorial_text_does_not_request_text(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    requests = batch_engine.create_requests(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    prompt = requests[1].prompt

    assert (
        "Editorial text inside the illustration"
        not in prompt
    )

    assert (
        "not a subtitle or caption"
        not in prompt
    )

    assert (
        "Avoid photorealism"
        in prompt
    )

    assert (
        "unnecessary text."
        in prompt
    )


def test_prompts_use_different_camera_motion(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    requests = batch_engine.create_requests(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    assert "Static camera." in requests[0].prompt
    assert "Slow gentle zoom in." in requests[1].prompt


def test_generate_returns_assets(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    assets = batch_engine.generate(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    assert len(assets) == 2

    for asset in assets:
        assert isinstance(asset, ImageAsset)
        assert asset.status == "completed"
        assert asset.file_path is not None


def test_generate_creates_image_files(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    assets = batch_engine.generate(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    for asset in assets:
        assert asset.file_path is not None

        image_path = Path(asset.file_path)

        assert image_path.exists()
        assert image_path.is_file()
        assert image_path.suffix == ".png"


def test_generate_preserves_scene_information(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    assets = batch_engine.generate(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    assert assets[0].image_id == "scene_001"
    assert assets[0].scene_id == "scene_001"

    assert assets[1].image_id == "scene_002"
    assert assets[1].scene_id == "scene_002"


def test_save_and_load_manifest(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    assets = batch_engine.generate(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    manifest_path = tmp_path / "image_manifest.json"

    batch_engine.save_manifest(
        assets,
        manifest_path,
    )

    assert manifest_path.exists()

    loaded_assets = batch_engine.load_manifest(
        manifest_path
    )

    assert loaded_assets == assets


def test_load_storyboard(
    tmp_path: Path,
) -> None:
    storyboard = create_test_storyboard()

    storyboard_path = tmp_path / "storyboard.json"

    storyboard_path.write_text(
        storyboard.model_dump_json(indent=2),
        encoding="utf-8",
    )

    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    loaded = batch_engine.load_storyboard(
        storyboard_path
    )

    assert loaded.topic == storyboard.topic
    assert len(loaded.scenes) == 2
    assert loaded.scenes[0].scene_id == "scene_001"


def test_generate_fails_for_empty_storyboard(
    tmp_path: Path,
) -> None:
    storyboard = Storyboard(
        topic="Empty Topic",
        target_duration_seconds=10,
        scenes=[],
        total_scene_duration_seconds=0.0,
        target_scene_duration_seconds=5.0,
    )

    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    with pytest.raises(ValueError):
        batch_engine.generate(
            storyboard=storyboard,
            output_directory=tmp_path,
        )


def test_generate_uses_custom_prompt_builder(
    tmp_path: Path,
) -> None:
    class CustomPromptBuilder(ImagePromptBuilder):
        def build(self, scene: StoryboardScene) -> str:
            return f"CUSTOM PROMPT: {scene.scene_id}"

    provider = MockImageProvider()
    image_engine = ImageEngine(provider)

    batch_engine = ImageBatchEngine(
        image_engine=image_engine,
        prompt_builder=CustomPromptBuilder(),
    )

    storyboard = create_test_storyboard()

    requests = batch_engine.create_requests(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    assert requests[0].prompt == (
        "CUSTOM PROMPT: scene_001"
    )

    assert requests[1].prompt == (
        "CUSTOM PROMPT: scene_002"
    )