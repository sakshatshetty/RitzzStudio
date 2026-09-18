from pathlib import Path

import pytest

from modules.image.batch import ImageBatchEngine
from modules.image.engine import ImageEngine
from modules.image.providers.mock import MockImageProvider
from modules.storyboard.models import (
    Storyboard,
    StoryboardScene,
)


def create_test_storyboard() -> Storyboard:
    """Create a small valid storyboard for testing."""

    return Storyboard(
        topic="Why Do Pirates Wear Eye Patches?",
        target_duration_seconds=15,
        total_scene_duration_seconds=15.0,
        target_scene_duration_seconds=5.0,
        scenes=[
            StoryboardScene(
                scene_id="scene_001",
                section_id="s1",
                start_seconds=0,
                duration_seconds=5,
                narration=(
                    "Why do pirates wear eye patches?"
                ),
                visual_style="stickman",
                visual_description=(
                    "A pirate standing on a wooden ship."
                ),
                character_action=(
                    "The pirate looks toward the viewer."
                ),
                background="Wooden pirate ship deck.",
                props=[
                    "eye patch",
                    "ship wheel",
                ],
                text_overlay="Why the eye patch?",
                camera_motion="static",
                transition="cut",
                research_sources=[
                    "source-1",
                ],
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
                narration=(
                    "The answer may surprise you."
                ),
                visual_style="stickman",
                visual_description=(
                    "A pirate touching his eye patch."
                ),
                character_action=(
                    "The pirate touches his eye patch."
                ),
                background="Wooden ship deck.",
                props=[
                    "eye patch",
                ],
                text_overlay="The surprising answer",
                camera_motion="slow_zoom_in",
                transition="cut",
                research_sources=[
                    "source-1",
                ],
                image_prompt=(
                    "Simple 2D cartoon stickman pirate "
                    "touching his eye patch on a wooden ship, "
                    "thick black outlines, flat colors."
                ),
            ),
            StoryboardScene(
                scene_id="scene_003",
                section_id="s2",
                start_seconds=10,
                duration_seconds=5,
                narration=(
                    "It was not always about an injury."
                ),
                visual_style="stickman",
                visual_description=(
                    "A pirate walking across the deck."
                ),
                character_action=(
                    "The pirate walks across the ship deck."
                ),
                background="Pirate ship deck.",
                props=[
                    "wooden barrel",
                ],
                text_overlay="Not always an injury",
                camera_motion="pan_right",
                transition="fade",
                research_sources=[
                    "source-2",
                ],
                image_prompt=(
                    "Simple 2D cartoon stickman pirate "
                    "walking across a wooden ship deck, "
                    "thick black outlines, flat colors."
                ),
            ),
        ],
    )


def test_load_storyboard(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    storyboard_file = (
        tmp_path / "storyboard.json"
    )

    storyboard_file.write_text(
        storyboard.model_dump_json(
            indent=2
        ),
        encoding="utf-8",
    )

    loaded = batch_engine.load_storyboard(
        storyboard_file
    )

    assert loaded.topic == storyboard.topic
    assert len(loaded.scenes) == 3
    assert loaded.target_duration_seconds == 15
    assert (
        loaded.total_scene_duration_seconds
        == 15
    )


def test_load_missing_storyboard(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    with pytest.raises(FileNotFoundError):
        batch_engine.load_storyboard(
            tmp_path / "missing.json"
        )


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

    assert len(requests) == 3

    assert requests[0].image_id == "scene_001"
    assert requests[0].scene_id == "scene_001"

    assert requests[1].image_id == "scene_002"
    assert requests[1].scene_id == "scene_002"

    assert requests[2].image_id == "scene_003"
    assert requests[2].scene_id == "scene_003"


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
    assert (
        "Simple 2D cartoon illustration"
        in prompt
    )
    assert (
        "thick black outlines"
        in prompt
    )
    assert (
        "flat colors"
        in prompt
    )
    assert (
        "very minimal shading"
        in prompt
    )
    assert (
        "YouTube explainer animation style"
        in prompt
    )

    # Landscape output.
    assert (
        "Landscape 16:9 composition."
        in prompt
    )

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

    # Editorial text.
    assert (
        'Editorial text inside the illustration: '
        '"Why the eye patch?".'
        in prompt
    )

    # New handwritten editorial typography.
    assert (
        "simple, clean, hand-drawn handwritten lettering"
        in prompt
    )

    assert (
        "casual handwritten marker or hand-lettered"
        in prompt
    )

    assert (
        "medium-large and clearly readable"
        in prompt
    )

    assert (
        "visually noticeable but still secondary"
        in prompt
    )

    assert (
        "plain black or plain white"
        in prompt
    )

    # Prevent the old oversized/decorative treatment.
    assert (
        "large headline text"
        in prompt
    )

    assert (
        "oversized display typography"
        in prompt
    )

    assert (
        "bold display typography"
        in prompt
    )

    assert (
        "yellow text"
        in prompt
    )

    assert (
        "thick text outlines"
        in prompt
    )

    assert (
        "3D text"
        in prompt
    )


def test_prompt_without_editorial_text_does_not_request_text(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    # Remove editorial text from scene 2 so
    # this test exercises the no-text path.
    storyboard.scenes[1].text_overlay = ""

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

    assert "NO TEXT." in prompt
    assert "NO TITLES." in prompt
    assert "NO HEADLINES." in prompt
    assert "NO LABELS." in prompt
    assert "NO ARROWS." in prompt
    assert "NO CAPTIONS." in prompt
    assert "NO SUBTITLES." in prompt
    assert "NO SPEECH BUBBLES." in prompt


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

    assert (
        "Static camera."
        in requests[0].prompt
    )

    assert (
        "Slow gentle zoom in."
        in requests[1].prompt
    )

    assert (
        "Gentle camera pan right."
        in requests[2].prompt
    )


def test_editorial_text_is_preserved_for_each_scene(
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

    assert (
        '"Why the eye patch?"'
        in requests[0].prompt
    )

    assert (
        '"The surprising answer"'
        in requests[1].prompt
    )

    assert (
        '"Not always an injury"'
        in requests[2].prompt
    )


def test_prompts_are_generated_from_scene_data(
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

    assert (
        "A pirate standing on a wooden ship."
        in requests[0].prompt
    )

    assert (
        "A pirate touching his eye patch."
        in requests[1].prompt
    )

    assert (
        "A pirate walking across the deck."
        in requests[2].prompt
    )


def test_prompts_are_not_scene_image_prompt_directly(
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

    assert (
        requests[0].prompt
        != storyboard.scenes[0].image_prompt
    )

    assert (
        requests[1].prompt
        != storyboard.scenes[1].image_prompt
    )

    assert (
        requests[2].prompt
        != storyboard.scenes[2].image_prompt
    )


def test_generate_all_images(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    output_directory = (
        tmp_path / "images"
    )

    assets = batch_engine.generate(
        storyboard=storyboard,
        output_directory=output_directory,
    )

    assert len(assets) == 3
    assert len(provider.calls) == 3

    for asset in assets:
        assert asset.status == "completed"

        file_path = asset.file_path
        assert file_path is not None

        assert Path(file_path).exists()


def test_scene_to_image_mapping(
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

    assert assets[2].image_id == "scene_003"
    assert assets[2].scene_id == "scene_003"


def test_failed_scene_is_preserved(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider(
        fail_scene_id="scene_002"
    )

    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    assets = batch_engine.generate(
        storyboard=storyboard,
        output_directory=tmp_path,
    )

    assert len(assets) == 3

    assert assets[0].status == "completed"

    assert assets[1].status == "failed"
    assert assets[1].error_message == (
        "Mock generation failure."
    )

    assert assets[2].status == "completed"


def test_save_and_load_manifest(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = create_test_storyboard()

    assets = batch_engine.generate(
        storyboard=storyboard,
        output_directory=(
            tmp_path / "images"
        ),
    )

    manifest_file = (
        tmp_path / "image_manifest.json"
    )

    batch_engine.save_manifest(
        assets,
        manifest_file,
    )

    assert manifest_file.exists()

    loaded = batch_engine.load_manifest(
        manifest_file
    )

    assert loaded == assets
    assert len(loaded) == 3


def test_manifest_missing_file(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    with pytest.raises(FileNotFoundError):
        batch_engine.load_manifest(
            tmp_path / "missing_manifest.json"
        )


def test_output_files_use_image_ids(
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

    first_file_path = assets[0].file_path
    second_file_path = assets[1].file_path
    third_file_path = assets[2].file_path

    assert first_file_path is not None
    assert second_file_path is not None
    assert third_file_path is not None

    assert (
        Path(first_file_path).name
        == "scene_001.png"
    )

    assert (
        Path(second_file_path).name
        == "scene_002.png"
    )

    assert (
        Path(third_file_path).name
        == "scene_003.png"
    )


def test_generate_fails_for_empty_storyboard(
    tmp_path: Path,
) -> None:
    provider = MockImageProvider()
    image_engine = ImageEngine(provider)
    batch_engine = ImageBatchEngine(image_engine)

    storyboard = Storyboard(
        topic="Why Do Pirates Wear Eye Patches?",
        target_duration_seconds=0,
        total_scene_duration_seconds=0.0,
        target_scene_duration_seconds=5.0,
        scenes=[],
    )

    with pytest.raises(
        ValueError,
        match=(
            "Cannot generate images from "
            "an empty storyboard."
        ),
    ):
        batch_engine.generate(
            storyboard=storyboard,
            output_directory=tmp_path,
        )