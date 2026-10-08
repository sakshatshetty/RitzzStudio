import re

import pytest

from modules.project.config import ProductionConfig
from modules.qa.engine import load_project_qa
from modules.storyboard.models import Storyboard, StoryboardScene
from modules.video.audio_timed_storyboard import AudioTimedStoryboardEngine
from modules.video.engine import VideoAssemblyEngine
from modules.video.sync_models import NarrationAlignment


def make_storyboard(lines: list[str], descriptions: list[str] | None = None):
    descriptions = descriptions or ["A visual for the sentence"] * len(lines)
    scenes = []
    for index, (line, description) in enumerate(
        zip(lines, descriptions, strict=True),
        start=1,
    ):
        sentence = line.strip()
        start = float((index - 1) * 2)
        scenes.append(
            StoryboardScene(
                scene_id=f"scene_{index:03}",
                section_id="s1",
                start_seconds=start,
                duration_seconds=2,
                narration=sentence,
                sentence_id=index,
                sentence=sentence,
                sentence_start_seconds=start,
                sentence_end_seconds=start + 2,
                visual_description=description,
                image_prompt="A hand-drawn cartoon illustration.",
            )
        )
    total = len(scenes) * 2
    return Storyboard(
        topic="Pirates",
        target_duration_seconds=round(total),
        scenes=scenes,
        total_scene_duration_seconds=total,
        target_scene_duration_seconds=None,
    )


def alignment_for(text: str, audio_duration: float):
    starts = [0.0] * len(text)
    ends = [0.0] * len(text)
    words = list(re.finditer(r"\S+", text))
    word_duration = audio_duration / len(words)
    for word_index, word in enumerate(words):
        word_start = word_index * word_duration
        char_duration = word_duration / len(word.group())
        for offset, char_index in enumerate(range(word.start(), word.end())):
            starts[char_index] = word_start + offset * char_duration
            ends[char_index] = word_start + (offset + 1) * char_duration
    for whitespace in re.finditer(r"\s+", text):
        next_word_index = next(
            (
                index
                for index, word in enumerate(words)
                if word.start() >= whitespace.end()
            ),
            len(words),
        )
        boundary = next_word_index * word_duration
        for char_index in range(whitespace.start(), whitespace.end()):
            starts[char_index] = ends[char_index] = boundary
    return NarrationAlignment(
        characters=list(text),
        character_start_times_seconds=starts,
        character_end_times_seconds=ends,
        audio_duration_seconds=audio_duration,
    )


@pytest.mark.parametrize("duration", [2.0, 7.0, 10.0])
def test_sentence_duration_is_taken_from_audio_without_minimum_or_maximum(
    duration: float,
):
    sentence = "The sailor waits beside the old wooden ship."
    storyboard = make_storyboard([sentence])
    alignment = alignment_for(sentence, duration)
    config = ProductionConfig(
        target_duration_seconds=480,
        minimum_duration_seconds=480,
        scene_minimum_duration_seconds=3,
        scene_maximum_duration_seconds=4,
    )

    timed = AudioTimedStoryboardEngine(production_config=config).build(
        storyboard,
        alignment,
    )

    assert len(timed.scenes) == 1
    scene = timed.scenes[0]
    assert scene.sentence_id == 1
    assert scene.sentence == sentence
    assert scene.start_seconds == pytest.approx(0)
    assert scene.duration_seconds == pytest.approx(duration)
    assert scene.sentence_end_seconds == pytest.approx(duration)
    assert scene.camera_motion == "static"
    assert scene.transition == "cut"


def test_two_sentences_always_create_two_images_with_exact_audio_cut_boundary():
    lines = ["The sailor hears footsteps.", "He hides below the cargo deck."]
    text = " ".join(lines)
    timed = AudioTimedStoryboardEngine().build(
        make_storyboard(lines, ["The same ship", "The same ship"]),
        alignment_for(text, 7),
    )

    assert len(timed.scenes) == 2
    assert [scene.narration for scene in timed.scenes] == lines
    assert timed.scenes[0].duration_seconds == pytest.approx(2.8)
    assert timed.scenes[1].start_seconds == pytest.approx(2.8)
    assert timed.scenes[0].start_seconds + timed.scenes[0].duration_seconds == (
        pytest.approx(timed.scenes[1].start_seconds)
    )
    assert timed.scenes[1].duration_seconds == pytest.approx(4.2)


def test_each_sentence_scene_requires_and_maps_to_exactly_one_image(tmp_path):
    lines = ["The sailor hears footsteps.", "He hides below the cargo deck."]
    timed = AudioTimedStoryboardEngine().build(
        make_storyboard(lines),
        alignment_for(" ".join(lines), 7),
    )
    image_directory = tmp_path / "images"
    image_directory.mkdir()
    for scene in timed.scenes:
        (image_directory / f"{scene.scene_id}.png").write_bytes(b"readable image")

    plan = VideoAssemblyEngine().create_plan(timed, image_directory)

    assert len(plan.clips) == len(timed.scenes) == 2
    assert [clip.scene_id for clip in plan.clips] == [
        scene.scene_id for scene in timed.scenes
    ]


def test_long_sentence_is_not_split_and_short_sentences_are_not_merged():
    lines = [
        "The pirate hides below deck while the crew searches the upper level.",
        "He waits.",
        "They leave.",
    ]
    text = " ".join(lines)
    timed = AudioTimedStoryboardEngine().build(
        make_storyboard(lines),
        alignment_for(text, 20),
    )

    assert len(timed.scenes) == len(lines)
    assert [scene.narration for scene in timed.scenes] == lines
    assert timed.scenes[0].duration_seconds > 7
    assert timed.scenes[1].duration_seconds > 0
    assert timed.scenes[2].duration_seconds > 0


def test_rejects_multiple_sentences_in_one_input_scene():
    text = "The sailor hears footsteps. He hides below deck."
    with pytest.raises(ValueError, match="exactly one complete sentence"):
        AudioTimedStoryboardEngine().build(
            make_storyboard([text]),
            alignment_for(text, 5),
        )


def test_neighbor_context_is_attached_but_current_sentence_remains_primary():
    lines = [
        "The sailor hears footsteps overhead.",
        "He hides below the cargo deck.",
        "The crew searches the upper deck.",
    ]
    timed = AudioTimedStoryboardEngine().build(
        make_storyboard(lines),
        alignment_for(" ".join(lines), 12),
    )

    scene = timed.scenes[1]
    prompt = scene.image_prompt
    assert "FULL PROJECT TOPIC: Pirates" in prompt
    assert "CURRENT SENTENCE — PRIMARY VISUAL INSTRUCTION: " + lines[1] in prompt
    assert "PREVIOUS SENTENCE — continuity context only: " + lines[0] in prompt
    assert "NEXT SENTENCE — continuity context only: " + lines[2] in prompt
    assert "Context must clarify the current sentence" in prompt
    assert "NO TEXT." in prompt


def test_sentence_qa_accepts_any_positive_hold_duration():
    storyboard = make_storyboard(["A long sentence stays on one image."])
    storyboard.scenes[0] = storyboard.scenes[0].model_copy(
        update={
            "duration_seconds": 10,
            "sentence_end_seconds": 10,
        }
    )
    storyboard.total_scene_duration_seconds = 10

    qa = AudioTimedStoryboardEngine._evaluate_storyboard(
        storyboard,
        ProductionConfig(
            target_duration_seconds=10,
            minimum_duration_seconds=10,
            scene_minimum_duration_seconds=3,
            scene_maximum_duration_seconds=4,
        ),
    )

    assert qa.status == "PASS"
    assert "minimum_scene_duration" not in qa.checks
    assert "maximum_scene_duration" not in qa.checks
    assert qa.checks["sentence_scene_mapping"] == "PASS"


def test_sentence_qa_fails_when_one_scene_contains_multiple_sentences():
    scene = make_storyboard(["One sentence."] ).scenes[0].model_copy(
        update={
            "narration": "One sentence. Another sentence.",
            "sentence": "One sentence. Another sentence.",
        }
    )
    storyboard = make_storyboard(["One sentence."])
    storyboard.scenes = [scene]

    qa = AudioTimedStoryboardEngine._evaluate_storyboard(storyboard)

    assert qa.status == "FAIL"
    assert qa.checks["sentence_scene_mapping"] == "FAIL"


def test_validate_alignment_detects_saved_timing_drift():
    lines = ["The sailor hears footsteps.", "He hides below deck."]
    alignment = alignment_for(" ".join(lines), 8)
    timed = AudioTimedStoryboardEngine().build(
        make_storyboard(lines),
        alignment,
    )
    timed.scenes[1].start_seconds += 0.2

    with pytest.raises(ValueError, match="timing does not match"):
        AudioTimedStoryboardEngine.validate_alignment(timed, alignment)


def test_save_storyboard_repairs_only_static_camera_and_hard_cut_requirements(
    tmp_path,
):
    storyboard = make_storyboard(["The pirate waits."])
    storyboard.scenes[0] = storyboard.scenes[0].model_copy(
        update={"camera_motion": "slow_zoom_in", "transition": "fade"}
    )
    output = tmp_path / "storyboard" / "storyboard_audio_timed.json"

    AudioTimedStoryboardEngine.save_storyboard(storyboard, output)

    attempts = load_project_qa(tmp_path).stages["storyboard"]
    assert [result.status for result in attempts] == ["FAIL", "PASS"]
    saved = Storyboard.model_validate_json(output.read_text(encoding="utf-8"))
    assert saved.scenes[0].camera_motion == "static"
    assert saved.scenes[0].transition == "cut"
    assert saved.scenes[0].duration_seconds == pytest.approx(2)
