import json
from pathlib import Path

import pytest

from modules.project.config import ProductionConfig
from scripts.run_storyboard_stage import build_audio_timed_storyboard


def _write_project(
    project_directory: Path,
    *,
    narration: str = "First image. Second scene. Last image.",
) -> None:
    storyboard_directory = project_directory / "storyboard"
    voice_directory = project_directory / "voice"
    image_directory = project_directory / "images"
    storyboard_directory.mkdir(parents=True)
    voice_directory.mkdir()
    image_directory.mkdir()
    sections = ["First image.", "Second scene.", "Last image."]
    scenes = [
        {
            "scene_id": f"scene_{index:03}",
            "narration": sentence,
            "visual_description": f"Visual description for scene {index}.",
            "image_prompt": f"Static image prompt for scene {index}.",
            "image_file": f"images/scene_{index:03}.png",
        }
        for index, sentence in enumerate(sections, start=1)
    ]
    (storyboard_directory / "storyboard_source.json").write_text(
        json.dumps(
            {
                "thumbnail_prompt": "A clean thumbnail prompt without rendered text.",
                "scenes": scenes,
            }
        ),
        encoding="utf-8",
    )
    (image_directory / "image_manifest.json").write_text(
        json.dumps([
            {
                "scene_id": scene["scene_id"],
                "status": "completed",
                "provider": "flow_mcp",
                "file_path": str(image_directory / Path(scene["image_file"]).name),
            }
            for scene in scenes
        ]),
        encoding="utf-8",
    )
    for scene in scenes:
        (image_directory / Path(scene["image_file"]).name).write_bytes(b"png")
    starts = [index * 0.1 for index in range(len(narration))]
    ends = [start + 0.1 for start in starts]
    (voice_directory / "narration_result.json").write_text(
        json.dumps(
            {
                "actual_duration_seconds": 5,
                "alignment": {
                    "characters": list(narration),
                    "character_start_times_seconds": starts,
                    "character_end_times_seconds": ends,
                },
            }
        ),
        encoding="utf-8",
    )


def _set_scene_start_times(
    project_directory: Path,
    *,
    second_scene_start: float,
    third_scene_start: float,
    audio_duration: float,
) -> None:
    narration_file = project_directory / "voice" / "narration_result.json"
    result = json.loads(narration_file.read_text(encoding="utf-8"))
    alignment = result["alignment"]
    characters = alignment["characters"]
    text = "".join(characters)
    anchors = [
        (0, 0.0),
        (text.index("Second scene."), second_scene_start),
        (text.index("Last image."), third_scene_start),
        (len(characters) - 1, audio_duration - 0.25),
    ]
    starts = []
    anchor_index = 0
    for character_index in range(len(characters)):
        while (
            anchor_index + 1 < len(anchors)
            and character_index > anchors[anchor_index + 1][0]
        ):
            anchor_index += 1
        left_index, left_time = anchors[anchor_index]
        right_index, right_time = anchors[
            min(anchor_index + 1, len(anchors) - 1)
        ]
        fraction = (
            0
            if right_index == left_index
            else (character_index - left_index) / (right_index - left_index)
        )
        starts.append(left_time + fraction * (right_time - left_time))
    alignment["character_start_times_seconds"] = starts
    alignment["character_end_times_seconds"] = [
        start + 0.001 for start in starts
    ]
    result["actual_duration_seconds"] = audio_duration
    narration_file.write_text(json.dumps(result), encoding="utf-8")


def _set_fragment_start_times(
    project_directory: Path,
    scene_start_times: list[float],
    audio_duration: float,
) -> None:
    source_file = project_directory / "storyboard" / "storyboard_source.json"
    source = json.loads(source_file.read_text(encoding="utf-8"))
    narration_file = project_directory / "voice" / "narration_result.json"
    result = json.loads(narration_file.read_text(encoding="utf-8"))
    alignment = result["alignment"]
    text = "".join(alignment["characters"])
    anchors = [(0, 0.0)]
    for scene, start_seconds in zip(
        source["scenes"], scene_start_times, strict=True
    ):
        anchors.append((text.index(scene["narration"].strip()), start_seconds))
    anchors.append((len(text) - 1, audio_duration - 0.25))
    anchors.sort()
    starts = []
    for character_index in range(len(text)):
        right_index = next(
            (
                index
                for index, (anchor_index, _) in enumerate(anchors)
                if anchor_index >= character_index
            ),
            len(anchors) - 1,
        )
        left_index, left_time = anchors[max(0, right_index - 1)]
        right_char_index, right_time = anchors[right_index]
        fraction = (
            0.0
            if right_char_index == left_index
            else (character_index - left_index)
            / (right_char_index - left_index)
        )
        starts.append(left_time + fraction * (right_time - left_time))
    alignment["character_start_times_seconds"] = starts
    alignment["character_end_times_seconds"] = [
        start + 0.001 for start in starts
    ]
    result["actual_duration_seconds"] = audio_duration
    narration_file.write_text(json.dumps(result), encoding="utf-8")


def test_times_supplied_scenes_to_character_alignment_with_static_hard_cuts(
    tmp_path,
):
    project_directory = tmp_path / "project"
    _write_project(project_directory)
    _set_scene_start_times(
        project_directory,
        second_scene_start=6.0,
        third_scene_start=12.0,
        audio_duration=17.5,
    )
    config = ProductionConfig(
        target_duration_seconds=60,
        minimum_duration_seconds=1,
        scene_minimum_duration_seconds=1,
        scene_maximum_duration_seconds=6,
    )

    storyboard = build_audio_timed_storyboard(
        project_directory,
        "Supplied topic",
        "First image. Second scene. Last image.",
        config,
    )

    assert len(storyboard.scenes) == 3
    assert storyboard.scenes[0].start_seconds == 0
    assert storyboard.scenes[1].start_seconds > 0
    assert storyboard.scenes[-1].start_seconds + storyboard.scenes[-1].duration_seconds == 17.5
    assert all(scene.camera_motion == "static" for scene in storyboard.scenes)
    assert all(scene.transition == "cut" for scene in storyboard.scenes)
    assert all(scene.image_prompt.startswith("Static image prompt") for scene in storyboard.scenes)
    assert all(scene.duration_seconds >= 3.0 for scene in storyboard.scenes)
    assert all(scene.duration_seconds <= 6.0 for scene in storyboard.scenes)
    saved = json.loads(
        (project_directory / "storyboard" / "storyboard_audio_timed.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(saved["scenes"]) == 3


def test_groups_phrase_fragments_until_the_sentence_is_complete(tmp_path):
    project_directory = tmp_path / "project"
    _write_project(
        project_directory,
        narration="First image continues clearly. Last image.",
    )
    source_file = project_directory / "storyboard" / "storyboard_source.json"
    source = json.loads(source_file.read_text(encoding="utf-8"))
    source["scenes"][0]["narration"] = "First image continues"
    source["scenes"][1]["narration"] = " clearly."
    source["scenes"][2]["narration"] = " Last image."
    source_file.write_text(json.dumps(source), encoding="utf-8")
    _set_fragment_start_times(
        project_directory,
        [0.0, 3.0, 6.0],
        audio_duration=9.0,
    )

    storyboard = build_audio_timed_storyboard(
        project_directory,
        "Supplied topic",
        "First image continues clearly. Last image.",
        ProductionConfig(
            target_duration_seconds=60,
            minimum_duration_seconds=1,
            scene_minimum_duration_seconds=3,
            scene_maximum_duration_seconds=8,
        ),
    )

    assert [scene.scene_id for scene in storyboard.scenes] == [
        "scene_001",
        "scene_003",
    ]
    assert [scene.narration for scene in storyboard.scenes] == [
        "First image continues clearly.",
        "Last image.",
    ]
    assert [scene.duration_seconds for scene in storyboard.scenes] == pytest.approx(
        [6.0, 3.0]
    )
    assert [scene.timing_boundary for scene in storyboard.scenes] == [
        "audio_start",
        "sentence",
    ]


def test_rejects_a_sentence_over_15_words_when_grouping_fragments(tmp_path):
    project_directory = tmp_path / "project"
    sentence = " ".join(f"word{index}" for index in range(1, 17)) + "."
    narration = f"{sentence} Final sentence."
    _write_project(project_directory, narration=narration)
    source_file = project_directory / "storyboard" / "storyboard_source.json"
    source = json.loads(source_file.read_text(encoding="utf-8"))
    source["scenes"][0]["narration"] = " ".join(
        f"word{index}" for index in range(1, 9)
    )
    source["scenes"][1]["narration"] = " " + " ".join(
        f"word{index}" for index in range(9, 17)
    ) + "."
    source["scenes"][2]["narration"] = " Final sentence."
    source_file.write_text(json.dumps(source), encoding="utf-8")
    _set_fragment_start_times(project_directory, [0.0, 3.0, 6.0], 9.0)

    with pytest.raises(
        ValueError,
        match="sentence has 16 words; the maximum is 15",
    ):
        build_audio_timed_storyboard(
            project_directory,
            "Supplied topic",
            narration,
            ProductionConfig(
                target_duration_seconds=60,
                minimum_duration_seconds=1,
                scene_minimum_duration_seconds=3,
                scene_maximum_duration_seconds=8,
            ),
        )


def test_combines_only_a_pair_of_one_word_sentences_for_a_short_hold(tmp_path):
    project_directory = tmp_path / "project"
    _write_project(project_directory, narration="Go. Now. Last image.")
    source_file = project_directory / "storyboard" / "storyboard_source.json"
    source = json.loads(source_file.read_text(encoding="utf-8"))
    source["scenes"][0]["narration"] = "Go."
    source["scenes"][1]["narration"] = " Now."
    source["scenes"][2]["narration"] = " Last image."
    source_file.write_text(json.dumps(source), encoding="utf-8")
    _set_fragment_start_times(
        project_directory,
        [0.0, 0.2, 2.5],
        audio_duration=5.5,
    )

    storyboard = build_audio_timed_storyboard(
        project_directory,
        "Supplied topic",
        "Go. Now. Last image.",
        ProductionConfig(
            target_duration_seconds=60,
            minimum_duration_seconds=1,
            scene_minimum_duration_seconds=3,
            scene_maximum_duration_seconds=8,
        ),
    )

    assert [scene.narration for scene in storyboard.scenes] == [
        "Go. Now.",
        "Last image.",
    ]
    assert [scene.duration_seconds for scene in storyboard.scenes] == pytest.approx(
        [2.5, 3.0]
    )


def test_does_not_merge_normal_short_sentences_to_reach_minimum(tmp_path):
    project_directory = tmp_path / "project"
    _write_project(project_directory)
    _set_scene_start_times(
        project_directory,
        second_scene_start=2.0,
        third_scene_start=4.0,
        audio_duration=7.5,
    )

    with pytest.raises(
        ValueError,
        match="one sentence per visual scene",
    ):
        build_audio_timed_storyboard(
            project_directory,
            "Supplied topic",
            "First image. Second scene. Last image.",
            ProductionConfig(
                target_duration_seconds=60,
                minimum_duration_seconds=1,
                scene_minimum_duration_seconds=3,
                scene_maximum_duration_seconds=8,
            ),
        )


@pytest.mark.parametrize(
    ("second_scene_start", "third_scene_start", "accepted"),
    [
        (6.0, 12.0, True),
        (6.001, 12.1, False),
    ],
)
def test_enforces_the_exact_scene_maximum(
    tmp_path,
    second_scene_start,
    third_scene_start,
    accepted,
):
    project_directory = tmp_path / "project"
    _write_project(project_directory)
    _set_scene_start_times(
        project_directory,
        second_scene_start=second_scene_start,
        third_scene_start=third_scene_start,
        audio_duration=17.5,
    )
    config = ProductionConfig(
        target_duration_seconds=60,
        minimum_duration_seconds=1,
        scene_minimum_duration_seconds=1,
        scene_maximum_duration_seconds=6,
    )

    if accepted:
        storyboard = build_audio_timed_storyboard(
            project_directory,
            "Supplied topic",
            "First image. Second scene. Last image.",
            config,
        )
        assert storyboard.scenes[0].duration_seconds == pytest.approx(6.0)
    else:
        with pytest.raises(
            ValueError,
            match="above the configured 6.000s maximum",
        ):
            build_audio_timed_storyboard(
                project_directory,
                "Supplied topic",
                "First image. Second scene. Last image.",
                config,
            )


def test_updates_resumed_creative_package_to_eight_second_scene_limit(
    tmp_path,
):
    project_directory = tmp_path / "project"
    _write_project(project_directory)
    _set_scene_start_times(
        project_directory,
        second_scene_start=8.0,
        third_scene_start=16.0,
        audio_duration=24.0,
    )
    (project_directory / "topic_selection.json").write_text(
        json.dumps({"source": "creative_package"}),
        encoding="utf-8",
    )
    config = ProductionConfig(
        target_duration_seconds=60,
        minimum_duration_seconds=1,
        scene_minimum_duration_seconds=1,
        scene_maximum_duration_seconds=6.6,
    )
    config_file = project_directory / "production_config.json"
    config_file.write_text(config.model_dump_json(), encoding="utf-8")

    storyboard = build_audio_timed_storyboard(
        project_directory,
        "Supplied topic",
        "First image. Second scene. Last image.",
        config,
    )

    assert storyboard.scenes[0].duration_seconds == pytest.approx(8.0)
    updated_config = json.loads(config_file.read_text(encoding="utf-8"))
    assert updated_config["scene_maximum_duration_seconds"] == pytest.approx(8.0)
    assert updated_config["scene_minimum_duration_seconds"] == pytest.approx(2.9)


@pytest.mark.parametrize(
    ("first_scene_duration", "accepted"),
    [
        (2.9, True),
        (2.972, True),
        (2.899, False),
    ],
)
def test_applies_audio_alignment_tolerance_to_creative_package_minimum(
    tmp_path,
    first_scene_duration,
    accepted,
):
    project_directory = tmp_path / "project"
    _write_project(project_directory)
    _set_scene_start_times(
        project_directory,
        second_scene_start=first_scene_duration,
        third_scene_start=6.0,
        audio_duration=9.0,
    )
    (project_directory / "topic_selection.json").write_text(
        json.dumps({"source": "creative_package"}),
        encoding="utf-8",
    )
    config = ProductionConfig(
        target_duration_seconds=60,
        minimum_duration_seconds=1,
        scene_minimum_duration_seconds=3.0,
        scene_maximum_duration_seconds=8.0,
    )

    if accepted:
        storyboard = build_audio_timed_storyboard(
            project_directory,
            "Supplied topic",
            "First image. Second scene. Last image.",
            config,
        )
        assert storyboard.scenes[0].duration_seconds == pytest.approx(
            first_scene_duration
        )
    else:
        with pytest.raises(
            ValueError,
            match="below the configured 2.900s minimum",
        ):
            build_audio_timed_storyboard(
                project_directory,
                "Supplied topic",
                "First image. Second scene. Last image.",
                config,
            )


def test_accepts_absolute_manifest_image_paths_for_relative_project_directory(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)
    project_directory = Path("projects") / "project"
    _write_project(project_directory)
    _set_scene_start_times(
        project_directory,
        second_scene_start=6.0,
        third_scene_start=12.0,
        audio_duration=17.5,
    )
    manifest_file = project_directory / "images" / "image_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    for asset in manifest:
        asset["file_path"] = str(
            (project_directory / "images" / f"{asset['scene_id']}.png").resolve()
        )
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    storyboard = build_audio_timed_storyboard(
        project_directory,
        "Supplied topic",
        "First image. Second scene. Last image.",
        ProductionConfig(
            target_duration_seconds=60,
            minimum_duration_seconds=1,
            scene_minimum_duration_seconds=1,
            scene_maximum_duration_seconds=6,
        ),
    )

    assert len(storyboard.scenes) == 3
    assert [scene.narration for scene in storyboard.scenes] == [
        "First image.",
        "Second scene.",
        "Last image.",
    ]


def test_rejects_missing_or_mismatched_flow_image_manifest(tmp_path):
    project_directory = tmp_path / "project"
    _write_project(project_directory)
    manifest_file = project_directory / "images" / "image_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest.pop()
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match the storyboard"):
        build_audio_timed_storyboard(
            project_directory,
            "Supplied topic",
            "First image. Second scene. Last image.",
            ProductionConfig(
                target_duration_seconds=60,
                minimum_duration_seconds=1,
                scene_minimum_duration_seconds=1,
                scene_maximum_duration_seconds=6,
            ),
        )


def test_rejects_storyboard_not_covering_the_exact_script(tmp_path):
    project_directory = tmp_path / "project"
    _write_project(project_directory)
    source = project_directory / "storyboard" / "storyboard_source.json"
    storyboard = json.loads(source.read_text(encoding="utf-8"))
    storyboard["scenes"][1]["narration"] = "Different narration."
    source.write_text(json.dumps(storyboard), encoding="utf-8")

    with pytest.raises(ValueError, match="Could not match storyboard narration"):
        build_audio_timed_storyboard(
            project_directory,
            "Supplied topic",
            "First image. Second scene. Last image.",
            ProductionConfig(
                target_duration_seconds=60,
                minimum_duration_seconds=1,
                scene_minimum_duration_seconds=1,
                scene_maximum_duration_seconds=6,
            ),
        )
