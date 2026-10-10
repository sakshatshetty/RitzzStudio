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
