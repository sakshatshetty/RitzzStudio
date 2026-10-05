from itertools import pairwise

import pytest

from modules.project.config import ProductionConfig
from modules.qa.engine import load_project_qa
from modules.storyboard.dynamic_engine import DynamicStoryboardEngine
from modules.storyboard.editorial_planner import EditorialDecision
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


def test_visual_change_waits_for_safe_natural_boundary_not_three_second_timer():
    lines = ["He waits.", " Then cannon fire erupts.", " Crew runs away."]
    storyboard = make_storyboard(lines, ["Pirate waiting", "A cannon fires", "Crew runs"])
    text = " ".join(lines)
    timed = AudioTimedStoryboardEngine().build(
        storyboard,
        alignment_for(text, 7, interval=0.06),
    )
    assert len(timed.scenes) == 2
    assert timed.scenes[0].narration == "He waits. Then cannon fire erupts."
    assert timed.scenes[1].start_seconds < 3
    assert timed.scenes[0].duration_seconds == timed.scenes[1].start_seconds


def test_production_callouts_are_one_word_and_spaced_three_or_four_scenes_apart():
    engine = DynamicStoryboardEngine()
    terms = [
        "evidence", "mystery", "myth", "history", "symbol", "vision",
        "adaptation", "survival", "culture", "theory", "proof", "legend",
    ]
    scenes = [
        make_storyboard(
            [f"The {term} changes everything."],
            [f"A visual representation of {term}"],
        ).scenes[0]
        for term in terms
    ]

    result = engine.apply_production_editorial_callouts(scenes)

    positions = [
        index for index, scene in enumerate(result)
        if scene.text_overlay
    ]
    assert positions
    assert positions[0] == 2
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
    from modules.storyboard.editorial_qa import review_editorial_callouts

    metrics = review_editorial_callouts(result)
    assert metrics.total_scenes == 12
    assert metrics.callouts_present == 3
    assert metrics.intentionally_skipped_callouts == 9
    assert metrics.average_scenes_between_callouts == 3.5
    assert metrics.longest_gap_between_callouts == 4
    assert all(
        scene.text_overlay
        or (
            scene.callout_not_warranted
            and scene.callout_not_warranted_reason
        )
        for scene in result
    )


def test_audio_timed_build_assigns_callouts_after_final_scene_grouping():
    callout_terms = [
        "evidence", "mystery", "myth", "history", "symbol", "vision",
        "adaptation", "survival", "culture", "theory", "proof", "legend",
    ]
    lines = [f"{term}." for term in callout_terms]
    visual_descriptions = [
        "An evidence scroll",
        "A mystery in fog",
        "A mythic mask",
        "A history book",
        "A symbolic flag",
        "A vision chart",
        "An adaptation tool",
        "A survival raft",
        "A culture festival",
        "A theory diagram",
        "A proof artifact",
        "A legend painting",
    ]
    storyboard = make_storyboard(lines, visual_descriptions)
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
    assert positions[0] == 2
    assert all(3 <= right - left <= 4 for left, right in pairwise(positions))
    assert all(
        len(timed.scenes[index].text_overlay.split()) == 1
        and timed.scenes[index].text_overlay.isupper()
        and len(timed.scenes[index].text_overlay) <= 20
        for index in positions
    )


def test_same_visual_idea_spans_multiple_sentences_without_timer_cut():
    lines = [
        "The city flooded every year.",
        "The river kept depositing new layers of soil.",
    ]
    storyboard = make_storyboard(lines, ["Same continuous pirate action"] * 3)
    text = " ".join(lines)
    timed = AudioTimedStoryboardEngine().build(storyboard, alignment_for(text, 10))
    assert len(timed.scenes) == 1
    assert timed.scenes[0].duration_seconds == 10
    assert all(scene.transition == "cut" for scene in timed.scenes)


def test_audio_timed_scene_splits_to_enforce_maximum_hold_without_natural_pause():
    lines = [
        "A continuing water treatment detail"
        for _ in range(20)
    ]
    storyboard = make_storyboard(lines, ["The same water treatment"] * len(lines))
    text = " ".join(lines)
    engine = AudioTimedStoryboardEngine(
        production_config=ProductionConfig(
            target_duration_seconds=480,
            minimum_duration_seconds=480,
            scene_maximum_duration_seconds=10,
        )
    )

    timed = engine.build(
        storyboard,
        alignment_for(text, 36, interval=36 / len(text)),
    )

    assert len(timed.scenes) > 1
    assert all(scene.duration_seconds <= 10 for scene in timed.scenes)
    assert timed.scenes[0].narration.startswith(lines[0])
    assert timed.scenes[-1].narration.endswith(lines[-1])


def test_sentence_end_and_visual_idea_change_create_a_scene():
    lines = [
        "The old city lies beneath the modern streets.",
        "Archaeologists lower a ladder into the excavation.",
    ]
    storyboard = make_storyboard(
        lines,
        ["A layered city beneath a modern street", "Archaeologists descend into a dig"],
    )
    timed = AudioTimedStoryboardEngine().build(
        storyboard,
        alignment_for(" ".join(lines), 8, interval=0.05),
    )

    assert len(timed.scenes) == 2
    assert timed.scenes[0].narration == lines[0]
    assert timed.scenes[1].narration == lines[1]


def test_section_boilerplate_does_not_hide_a_visual_idea_change():
    lines = [
        "The old city lies beneath the modern streets.",
        "Archaeologists lower a ladder into the excavation.",
    ]
    storyboard = make_storyboard(lines, ["", ""])
    for scene in storyboard.scenes:
        scene.visual_description = (
            "Simple hand-drawn stick-man explainer scene illustrating the idea "
            "in 'History'. The character should visually represent this narration: "
            f"{scene.narration}"
        )

    timed = AudioTimedStoryboardEngine().build(
        storyboard,
        alignment_for(" ".join(lines), 8, interval=0.05),
    )

    assert len(timed.scenes) == 2


def test_natural_pause_can_create_boundary_without_sentence_punctuation():
    lines = ["The sailor waits", "then the cannon fires"]
    storyboard = make_storyboard(lines, ["A sailor waits", "A cannon fires"])
    text = " ".join(lines)
    pause_start = text.index("then")
    starts = []
    ends = []
    for index in range(len(text)):
        start = index * 0.04 + (0.95 if index >= pause_start else 0)
        starts.append(start)
        ends.append(start + 0.02)
    alignment = NarrationAlignment(
        characters=list(text),
        character_start_times_seconds=starts,
        character_end_times_seconds=ends,
        audio_duration_seconds=6,
    )

    timed = AudioTimedStoryboardEngine().build(storyboard, alignment)

    assert len(timed.scenes) == 2
    assert timed.scenes[0].narration == lines[0]


def test_adjacent_same_visual_beats_are_merged_and_scene_duration_stays_safe():
    lines = [
        "The pirate studies the old map.",
        "The pirate traces the route on the map.",
    ]
    storyboard = make_storyboard(lines, ["Pirate studying map"] * 2)
    timed = AudioTimedStoryboardEngine().build(
        storyboard,
        alignment_for(" ".join(lines), 8, interval=0.06),
    )

    assert len(timed.scenes) == 1
    assert timed.scenes[0].duration_seconds >= 1.5
    assert "DO NOT DRAW EDITORIAL CALLOUT TEXT." in timed.scenes[0].image_prompt


def test_repeated_composition_gets_a_meaningful_variation_prompt():
    lines = [
        "The captain studies a map carefully.",
        "The captain confronts the crew about the mutiny.",
    ]
    storyboard = make_storyboard(
        lines,
        ["A captain reading a map", "A captain confronting the crew"],
    )
    storyboard.scenes[0].character_action = "The captain stands and looks ahead."
    storyboard.scenes[1].character_action = storyboard.scenes[0].character_action
    storyboard.scenes[0].background = "The same ship deck."
    storyboard.scenes[1].background = storyboard.scenes[0].background
    timed = AudioTimedStoryboardEngine().build(
        storyboard,
        alignment_for(" ".join(lines), 8, interval=0.06),
    )

    assert len(timed.scenes) == 2
    assert "meaningfully different composition" in timed.scenes[1].visual_description


def test_production_callouts_are_not_forced_without_a_relevant_concept():
    scenes = [
        make_storyboard(
            [f"Ordinary sequence number {index} continues."],
            [f"Simple everyday action number {index}"],
        ).scenes[0]
        for index in range(12)
    ]

    result = DynamicStoryboardEngine().apply_production_editorial_callouts(scenes)

    assert not any(scene.text_overlay for scene in result)
    assert all(
        scene.callout_not_warranted
        and scene.callout_not_warranted_reason
        for scene in result
    )
    from modules.storyboard.editorial_qa import review_editorial_callouts

    qa = review_editorial_callouts(result)
    assert qa.status == "PASS"
    assert qa.callouts_present == 0
    assert qa.intentionally_skipped_callouts == 12


def test_planner_omission_is_unexpected_missing_not_an_implicit_skip():
    class IncompletePlanner:
        def plan(self, contexts):
            return {
                1: EditorialDecision(
                    callout_not_warranted=True,
                    reason="This opening scene is a setup beat.",
                )
            }

    scenes = [
        make_storyboard(
            [f"Ordinary sequence continues in scene {index}."],
            [f"A simple everyday action numbered {index}"],
        ).scenes[0]
        for index in range(5)
    ]
    result = DynamicStoryboardEngine(
        editorial_planner=IncompletePlanner(),
    ).apply_production_editorial_callouts(scenes)

    from modules.storyboard.editorial_qa import review_editorial_callouts

    qa = review_editorial_callouts(result)
    assert qa.unexpected_missing_callouts == 4
    assert qa.status == "REVIEW"


def test_review_failure_blocks_approval_but_review_remains_reviewable():
    from scripts.run_render_stage import _reject_semantic_qa_fail

    with pytest.raises(RuntimeError, match="semantic QA"):
        _reject_semantic_qa_fail("FAIL")
    _reject_semantic_qa_fail("REVIEW")


def test_audio_timed_storyboard_save_records_callout_review(tmp_path):
    storyboard = make_storyboard(["The pirate waits."], ["A pirate on deck"])
    storyboard.scenes[0].duration_seconds = 2
    storyboard.scenes[0].text_overlay = "THE MYTH"
    storyboard.scenes[0].camera_motion = "slow_zoom_in"
    storyboard.scenes[0].transition = "fade"
    storyboard.total_scene_duration_seconds = 2
    output = tmp_path / "storyboard" / "storyboard_audio_timed.json"

    AudioTimedStoryboardEngine.save_storyboard(storyboard, output)

    attempts = load_project_qa(tmp_path).stages["storyboard"]
    assert [result.status for result in attempts] == ["FAIL", "PASS"]
    assert attempts[0].checks["timeline_coverage"] == "PASS"
    assert attempts[0].checks["static_camera"] == "FAIL"
    assert attempts[0].checks["hard_cuts"] == "FAIL"
    assert attempts[0].metrics["total_scenes"] == 1
    assert attempts[0].metrics["malformed_callouts"] == 1
    assert attempts[0].details["scene_001"] == "malformed_callout"
    repaired = Storyboard.model_validate_json(output.read_text())
    assert repaired.scenes[0].camera_motion == "static"
    assert repaired.scenes[0].transition == "cut"
