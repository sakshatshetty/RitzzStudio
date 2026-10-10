"""Timestamp the user-supplied Flow scenes against actual narration alignment."""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.project.config import ProductionConfig
from modules.project.creative_package import CreativeStoryboard, _compact_text
from modules.project.manager import ProjectManager
from modules.storyboard.models import Storyboard, StoryboardScene
from modules.video.sync_engine import VideoSynchronizationEngine


def build_audio_timed_storyboard(
    project_directory: Path,
    project_title: str,
    script_text: str,
    production_config: ProductionConfig,
) -> Storyboard:
    source_file = project_directory / "storyboard" / "storyboard_source.json"
    narration_file = project_directory / "voice" / "narration_result.json"
    manifest_file = project_directory / "images" / "image_manifest.json"
    image_directory = project_directory / "images"
    if not source_file.is_file() or not narration_file.is_file():
        raise FileNotFoundError(
            "The supplied storyboard or aligned narration is missing."
        )
    source = CreativeStoryboard.model_validate_json(
        source_file.read_text(encoding="utf-8")
    )
    alignment = VideoSynchronizationEngine.load_narration_alignment(narration_file)
    VideoSynchronizationEngine._validate_alignment(alignment)
    aligned_text = "".join(alignment.characters)
    if _compact_text(aligned_text) != _compact_text(script_text):
        raise ValueError(
            "Narration alignment does not match the immutable supplied script."
        )
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if not isinstance(manifest, list):
        raise TypeError("The imported Flow image manifest must contain a list.")
    assets_by_scene = {
        asset.get("scene_id"): asset
        for asset in manifest
        if isinstance(asset, dict)
    }
    expected_scene_ids = [scene.scene_id for scene in source.scenes]
    if len(assets_by_scene) != len(expected_scene_ids) or set(assets_by_scene) != set(
        expected_scene_ids
    ):
        raise ValueError(
            "Imported Flow image manifest does not match the storyboard scene IDs."
        )

    source_scenes = []
    for scene in source.scenes:
        asset = assets_by_scene[scene.scene_id]
        image_path = image_directory / Path(scene.image_file).name
        if (
            asset.get("status") != "completed"
            or asset.get("provider") != "flow_mcp"
            or asset.get("file_path") != str(image_path)
            or not image_path.is_file()
            or image_path.stat().st_size == 0
        ):
            raise ValueError(
                f"{scene.scene_id} does not have its validated imported Flow image."
            )
        source_scenes.append(
            StoryboardScene(
                scene_id=scene.scene_id,
                section_id="supplied_storyboard",
                start_seconds=0,
                duration_seconds=1,
                narration=scene.narration,
                visual_description=scene.visual_description,
                image_prompt=scene.image_prompt,
                camera_motion="static",
                transition="cut",
            )
        )

    source_storyboard = Storyboard(
        topic=project_title,
        target_duration_seconds=production_config.target_duration_seconds,
        scenes=source_scenes,
        total_scene_duration_seconds=production_config.target_duration_seconds,
        target_scene_duration_seconds=3.0,
    )
    matches = VideoSynchronizationEngine()._match_scene_narration(
        source_storyboard,
        alignment,
    )
    timed_scenes: list[StoryboardScene] = []
    for index, (scene, match) in enumerate(
        zip(source_scenes, matches, strict=True)
    ):
        start = 0.0 if index == 0 else match["start_seconds"]
        end = (
            matches[index + 1]["start_seconds"]
            if index + 1 < len(matches)
            else alignment.audio_duration_seconds
        )
        duration = end - start
        if duration < production_config.scene_minimum_duration_seconds:
            raise ValueError(
                f"{scene.scene_id} holds for {duration:.3f}s, below the configured "
                f"{production_config.scene_minimum_duration_seconds:.3f}s minimum."
            )
        if duration > production_config.scene_maximum_duration_seconds:
            raise ValueError(
                f"{scene.scene_id} holds for {duration:.3f}s, above the configured "
                f"{production_config.scene_maximum_duration_seconds:.3f}s maximum. "
                "Split long narration across additional prepared scenes."
            )
        timed_scenes.append(
            scene.model_copy(
                update={
                    "sentence_id": index + 1,
                    "sentence": scene.narration,
                    "sentence_start_seconds": match["start_seconds"],
                    "sentence_end_seconds": match["end_seconds"],
                    "start_seconds": start,
                    "duration_seconds": duration,
                    "previous_sentence": (
                        source_scenes[index - 1].narration if index else ""
                    ),
                    "next_sentence": (
                        source_scenes[index + 1].narration
                        if index + 1 < len(source_scenes)
                        else ""
                    ),
                    "timing_boundary": "audio_start" if index == 0 else "sentence",
                    "camera_motion": "static",
                    "transition": "cut",
                }
            )
        )
    result = Storyboard(
        topic=project_title,
        target_duration_seconds=round(alignment.audio_duration_seconds),
        scenes=timed_scenes,
        total_scene_duration_seconds=alignment.audio_duration_seconds,
        target_scene_duration_seconds=3.0,
    )
    output_file = project_directory / "storyboard" / "storyboard_audio_timed.json"
    output_file.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(
        f"Audio-timed supplied storyboard: {output_file} "
        f"({len(result.scenes)} scenes, {alignment.audio_duration_seconds:.3f}s)."
    )
    return result


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    project_manager = ProjectManager(Path("projects"))
    project = project_manager.load_project(project_id)
    project_directory = project_manager.get_project_path(project)
    script_file = project_directory / "script" / "script.json"
    config_file = project_directory / "production_config.json"
    script = json.loads(script_file.read_text(encoding="utf-8"))
    script_text = " ".join(
        section["narration"] for section in script.get("sections", [])
    )
    production_config = ProductionConfig.model_validate_json(
        config_file.read_text(encoding="utf-8")
    )
    build_audio_timed_storyboard(
        project_directory,
        project.title,
        script_text,
        production_config,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
