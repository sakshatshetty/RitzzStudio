from pathlib import Path

import pytest

from modules.image.batch import ImageBatchEngine
from modules.image.engine import ImageEngine
from modules.image.providers.mock import MockImageProvider
from modules.image.models import ImageAsset
from modules.storyboard.models import Storyboard, StoryboardScene


def create_test_storyboard() -> Storyboard:
    """Create a small storyboard for image batch tests."""
    scenes = [
        StoryboardScene(
            scene_id="scene_001",
            section_id="s1",
            start_seconds=0,
            duration_seconds=5,
            narration="A pirate stands on a wooden ship.",
            visual_style="stickman",
            visual_description=(
                "A pirate standing on a wooden ship."
            ),
            character_action=(
                "The pirate looks toward the viewer."
            ),
            background="Wooden pirate ship deck.",
            props=["eye patch", "ship wheel"],
            text_overlay="Why the eye patch?",
            camera_motion="static",
            transition="cut",
            research_sources=["source_1"],
            image_prompt=(
                "Simple 2D cartoon stickman pirate "
                "standing on a wooden ship, thick black "
                "outlines, flat colors."
            ),
        ),
        StoryboardScene(
            scene_id="scene_002",
            section_id="s1",
            start_seconds=5,
            duration_seconds=5,
            narration="The pirate points toward the horizon.",
            visual_style="stickman",
            visual_description=(
                "A pirate pointing toward the horizon."
            ),
            character_action=(
                "The pirate points toward the horizon."
            ),
            background="Ocean and distant islands.",
            props=["telescope"],
            text_overlay="",
            camera_motion="slow_zoom_in",
            transition="cut",
            research_sources=["source_1"],
            image_prompt=(
                "Simple 2D cartoon stickman pirate "
                "pointing toward the horizon."
            ),
        ),
    ]

    return Storyboard(
        topic="Why Do Pirates Wear Eye Patches?",
        target_duration_seconds=10,
        scenes=scenes,
        total_scene_duration_seconds=10,
        target_scene_duration_seconds=5,
    )


def test_load_storyboard(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    storyboard_file = tmp_path / "storyboard.json"
    storyboard_file.write_text(
        storyboard.model_dump_json(indent=2),
        encoding="utf-8",
    )

    loaded = batch_engine.load_storyboard(
        storyboard_file
    )

    assert loaded.topic == storyboard.topic
    assert len(loaded.scenes) == 2
    assert loaded.scenes[0].scene_id == "scene_001"


def test_load_storyboard_missing_file(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    missing_file = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError):
        batch_engine.load_storyboard(missing_file)


def test_create_requests(
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

    assert requests[0].image_id == "scene_001"
    assert requests[0].scene_id == "scene_001"
    assert requests[0].output_directory == str(tmp_path)

    assert requests[1].image_id == "scene_002"
    assert requests[1].scene_id == "scene_002"


def test_requests_match_storyboard_scenes(
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

    for request, scene in zip(
        requests,
        storyboard.scenes,
        strict=True,
    ):
        assert request.image_id == scene.scene_id
        assert request.scene_id == scene.scene_id
        assert request.output_directory == str(tmp_path)


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

    assert (
        "Simple 2D stickman cartoon illustration"
        in prompt
    )
    assert "thick black outlines" in prompt
    assert "flat colors" in prompt
    assert "minimal shading" in prompt

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
    assert "Props: eye patch, ship wheel." in prompt
    assert (
        "Text overlay: Why the eye patch?."
        in prompt
    )
    assert "Camera: static composition" in prompt
    assert "Avoid photorealism" in prompt


def test_create_requests_uses_custom_prompt_builder(
    tmp_path: Path,
) -> None:
    from modules.image.prompt_builder import ImagePromptBuilder

    provider = MockImageProvider()
    image_engine = ImageEngine(provider)

    custom_style = (
        "Custom Ritzz visual style, "
        "simple cartoon illustration."
    )

    prompt_builder = ImagePromptBuilder(
        base_style=custom_style,
    )

    batch_engine = ImageBatchEngine(
        image_engine=image_engine,
        prompt_builder=prompt_builder,
    )

    storyboard = create_test_storyboard()

    requests = batch_engine.create_requests(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    assert custom_style in requests[0].prompt
    assert (
        "Scene: A pirate standing on a wooden ship."
        in requests[0].prompt
    )


def test_generate_creates_assets(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    output_directory = tmp_path / "images"

    assets = batch_engine.generate(
        storyboard=storyboard,
        output_directory=output_directory,
    )

    assert len(assets) == 2

    for asset in assets:
        assert isinstance(asset, ImageAsset)
        assert asset.status == "completed"
        assert asset.file_path is not None
        assert Path(asset.file_path).exists()


def test_generate_calls_provider_for_each_scene(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    batch_engine.generate(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    assert len(provider.calls) == 2
    assert provider.calls[0].scene_id == "scene_001"
    assert provider.calls[1].scene_id == "scene_002"


def test_generate_handles_failed_image(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider(
        fail_scene_id="scene_002",
    )

    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    assets = batch_engine.generate(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    assert len(assets) == 2

    assert assets[0].status == "completed"
    assert assets[0].file_path is not None

    assert assets[1].status == "failed"
    assert assets[1].file_path is None
    assert (
        assets[1].error_message
        == "Mock generation failure."
    )


def test_save_and_load_manifest(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    assets = batch_engine.generate(
        storyboard=storyboard,
        output_directory=tmp_path / "images",
    )

    manifest_file = tmp_path / "manifest.json"

    batch_engine.save_manifest(
        assets=assets,
        output_file=manifest_file,
    )

    assert manifest_file.exists()

    loaded_assets = batch_engine.load_manifest(
        manifest_file
    )

    assert len(loaded_assets) == 2
    assert loaded_assets[0].image_id == "scene_001"
    assert loaded_assets[1].image_id == "scene_002"
    assert loaded_assets[0].status == "completed"
    assert loaded_assets[1].status == "completed"


def test_load_manifest_missing_file(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    missing_file = tmp_path / "missing_manifest.json"

    with pytest.raises(FileNotFoundError):
        batch_engine.load_manifest(missing_file)