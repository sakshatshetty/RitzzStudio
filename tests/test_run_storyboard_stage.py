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


def test_times_supplied_scenes_to_character_alignment_with_static_hard_cuts(
    tmp_path,
):
    project_directory = tmp_path / "project"
    _write_project(project_directory)
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
    assert storyboard.scenes[-1].start_seconds + storyboard.scenes[-1].duration_seconds == 5
    assert all(scene.camera_motion == "static" for scene in storyboard.scenes)
    assert all(scene.transition == "cut" for scene in storyboard.scenes)
    assert all(scene.image_prompt.startswith("Static image prompt") for scene in storyboard.scenes)
    saved = json.loads(
        (project_directory / "storyboard" / "storyboard_audio_timed.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(saved["scenes"]) == 3


@pytest.mark.parametrize(
    ("second_scene_start", "third_scene_start", "accepted"),
    [
        (6.083, 12.0, True),
        (6.101, 12.1, False),
    ],
)
def test_allows_only_small_scene_maximum_timing_overage(
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
        assert storyboard.scenes[0].duration_seconds == pytest.approx(6.083)
    else:
        with pytest.raises(
            ValueError,
            match="above the configured 6.000s maximum by more than the 0.100s",
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
