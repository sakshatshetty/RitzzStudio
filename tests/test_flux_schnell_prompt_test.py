import pytest

from modules.storyboard.models import StoryboardScene
from scripts.test_flux_schnell_pilot import build_trial_prompt


def scene(scene_id: str, text_overlay: str = "") -> StoryboardScene:
    return StoryboardScene(
        scene_id=scene_id,
        section_id="section_001",
        start_seconds=0,
        duration_seconds=4,
        narration="A pirate scene.",
        visual_description="A colorful pirate on a ship.",
        image_prompt="A colorful pirate on a ship.",
        text_overlay=text_overlay,
    )


@pytest.mark.parametrize("scene_id", ["scene_001", "scene_004"])
def test_non_editorial_trial_prompt_requests_color_and_no_text(scene_id: str) -> None:
    prompt = build_trial_prompt(scene(scene_id))

    assert "entire scene in color" in prompt
    assert "Do not include any words" in prompt
    assert "ICONIC" not in prompt


@pytest.mark.parametrize(
    ("scene_id", "word"),
    [("scene_002", "ICONIC"), ("scene_005", "ACCURACY")],
)
def test_editorial_trial_prompt_limits_black_to_exact_callout(
    scene_id: str,
    word: str,
) -> None:
    prompt = build_trial_prompt(scene(scene_id, word))

    assert f'uppercase word "{word}"' in prompt
    assert "Black applies only to these letters" in prompt
    assert "entire scene in color" in prompt
    assert "No other writing" in prompt


def test_editorial_prompt_must_match_storyboard_word() -> None:
    with pytest.raises(ValueError, match="does not match"):
        build_trial_prompt(scene("scene_002", "SYMBOL"))


def test_unknown_scene_has_no_test_prompt() -> None:
    with pytest.raises(ValueError, match="No FLUX trial prompt"):
        build_trial_prompt(scene("scene_999"))
