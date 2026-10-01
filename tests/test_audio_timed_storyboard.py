from itertools import pairwise

from modules.qa.engine import load_project_qa
from modules.storyboard.dynamic_engine import DynamicStoryboardEngine
from modules.storyboard.models import Storyboard, StoryboardScene
from modules.video.audio_timed_storyboard import AudioTimedStoryboardEngine
from modules.video.sync_models import NarrationAlignment


def make_storyboard(lines, descriptions):
    scenes = []
    for index, (line, description) in enumerate(zip(lines, descriptions), start=1):
        scenes.append(StoryboardScene(scene_id=f"scene_{index:03}", section_id="s1",
            start_seconds=(index - 1) * 2, duration_seconds=2, narration=line,
            visual_description=description + " Focus specifically on this visual beat: " + line,
            image_prompt="A simple cartoon illustration."))
    return Storyboard(topic="Pirates", target_duration_seconds=10, scenes=scenes,
        total_scene_duration_seconds=10, target_scene_duration_seconds=2)


def alignment_for(text, audio_duration, interval=0.1):
    starts, ends = [], []
    for index in range(len(text)):
        starts.append(index * interval)
        ends.append((index + 1) * interval)
    return NarrationAlignment(characters=list(text), character_start_times_seconds=starts,
        character_end_times_seconds=ends, audio_duration_seconds=audio_duration)


def test_coalesces_fragments_of_same_narrative_and_uses_audio_times():
    lines = ["The pirate looks across", " the deck and raises", " a sail to the wind."]
    storyboard = make_storyboard(lines, ["Pirate on deck"] * 3)
    text = " ".join(lines)
    timed = AudioTimedStoryboardEngine().build(storyboard, alignment_for(text, 10, interval=0.01))
    assert len(timed.scenes) == 1
    assert timed.scenes[0].narration == " ".join(part.strip() for part in lines)
    assert timed.scenes[0].start_seconds == 0
    assert timed.scenes[0].duration_seconds == 10
    assert timed.scenes[0].image_prompt != "audio-timed placeholder"


def test_short_narrative_change_waits_for_three_second_hold():
    lines = ["He waits.", " Then cannon fire erupts.", " Crew runs away."]
    storyboard = make_storyboard(lines, ["Pirate waiting", "A cannon fires", "Crew runs"])
    text = " ".join(lines)
    timed = AudioTimedStoryboardEngine().build(storyboard, alignment_for(text, 7))
    assert len(timed.scenes) == 2
    assert timed.scenes[0].narration == "He waits. Then cannon fire erupts."
    assert timed.scenes[1].start_seconds >= 3
    assert timed.scenes[0].duration_seconds == timed.scenes[1].start_seconds


def test_production_callouts_are_one_word_and_spaced_three_or_four_scenes_apart():
    engine = DynamicStoryboardEngine()
    scenes = [
        make_storyboard(["A curious historical detail."], ["A single simple illustration"]).scenes[0]
        for _ in range(12)
    ]

    result = engine.apply_production_editorial_callouts(scenes)

    positions = [
        index for index, scene in enumerate(result)
        if scene.text_overlay
    ]
    assert positions
    assert positions[0] == 3
    assert all(
        3 <= right - left <= 4
        for left, right in pairwise(positions)
    )
    assert all(
        len(result[index].text_overlay.split()) == 1
        and result[index].text_overlay.isupper()
        and len(result[index].text_overlay) <= 20
        for index in positions
    )


def test_audio_timed_build_assigns_callouts_after_final_scene_grouping():
    lines = [f"Beat {index:02} is clear." for index in range(12)]
    storyboard = make_storyboard(lines, [f"Visual beat {index:02}" for index in range(12)])
    characters, starts, ends = [], [], []
    for index, line in enumerate(lines):
        base = index * 3.2
        step = 2.4 / len(line)
        for character_index, character in enumerate(line):
            start = base + character_index * step
            characters.append(character)
            starts.append(start)
            ends.append(start + step * 0.8)
        if index < len(lines) - 1:
            characters.append(" ")
            starts.append(base + 2.6)
            ends.append(base + 2.7)

    alignment = NarrationAlignment(
        characters=characters,
        character_start_times_seconds=starts,
        character_end_times_seconds=ends,
        audio_duration_seconds=12 * 3.2,
    )
    timed = AudioTimedStoryboardEngine().build(storyboard, alignment)

    assert len(timed.scenes) == 12
    positions = [
        index for index, scene in enumerate(timed.scenes)
        if scene.text_overlay
    ]
    assert positions
    assert positions[0] == 3
    assert all(3 <= right - left <= 4 for left, right in pairwise(positions))
    assert all(
        len(timed.scenes[index].text_overlay.split()) == 1
        and timed.scenes[index].text_overlay.isupper()
        and len(timed.scenes[index].text_overlay) <= 20
        for index in positions
    )


def test_same_narrative_is_split_only_after_three_seconds():
    lines = ["First short narration beat", "Second short narration beat", "Third short narration beat"]
    storyboard = make_storyboard(lines, ["Same continuous pirate action"] * 3)
    text = " ".join(lines)
    timed = AudioTimedStoryboardEngine().build(storyboard, alignment_for(text, 10))
    assert len(timed.scenes) == 2
    assert timed.scenes[0].duration_seconds >= 3
    assert timed.scenes[1].duration_seconds >= 3


def test_audio_timed_storyboard_save_records_callout_review(tmp_path):
    storyboard = make_storyboard(["The pirate waits."], ["A pirate on deck"])
    storyboard.scenes[0].duration_seconds = 2
    storyboard.scenes[0].text_overlay = "THE MYTH"
    storyboard.total_scene_duration_seconds = 2
    output = tmp_path / "storyboard" / "storyboard_audio_timed.json"

    AudioTimedStoryboardEngine.save_storyboard(storyboard, output)

    result = load_project_qa(tmp_path).stages["storyboard"][-1]
    assert result.status == "REVIEW"
    assert result.checks["timeline_coverage"] == "PASS"
    assert result.checks["editorial_format"] == "REVIEW"
    assert "single uppercase word" in result.findings[0]
