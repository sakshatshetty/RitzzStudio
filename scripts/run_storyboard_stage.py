"""Timestamp the user-supplied Flow scenes against actual narration alignment."""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.project.config import ProductionConfig
from modules.project.creative_package import (
    CREATIVE_PACKAGE_MAX_SCENE_WORDS,
    CREATIVE_PACKAGE_SCENE_MINIMUM_DURATION_SECONDS,
    CREATIVE_PACKAGE_SCENE_MAXIMUM_DURATION_SECONDS,
    CreativeStoryboard,
    _compact_text,
    split_narration_sentences,
)
from modules.project.manager import ProjectManager
from modules.storyboard.models import Storyboard, StoryboardScene
from modules.video.sync_engine import VideoSynchronizationEngine


TARGET_SCENE_DURATION_SECONDS = 5.0


def _scene_ending_boundary(narration: str) -> str | None:
    ending = narration.rstrip()
    while ending and ending[-1] in "\"'”’)]}":
        ending = ending[:-1].rstrip()
    if ending and ending[-1] in ".!?…":
        return "sentence"
    return None


def _is_one_word_sentence_pair(narration: str) -> bool:
    sentences = split_narration_sentences(narration)
    return len(sentences) == 2 and all(
        len(sentence.split()) == 1 for sentence in sentences
    )


def _first_grouping_failure(
    scenes: list[StoryboardScene],
    scene_matches: list[dict[str, float]],
    audio_duration_seconds: float,
    *,
    maximum_duration_seconds: float,
) -> str:
    sentence_start_index = 0
    for end_index, scene in enumerate(scenes):
        is_final_scene = end_index == len(scenes) - 1
        if not is_final_scene and _scene_ending_boundary(scene.narration) != "sentence":
            continue
        narration = " ".join(
            item.narration.strip()
            for item in scenes[sentence_start_index : end_index + 1]
        )
        sentences = split_narration_sentences(narration)
        start_seconds = (
            0.0
            if sentence_start_index == 0
            else scene_matches[sentence_start_index]["start_seconds"]
        )
        end_seconds = (
            scene_matches[end_index + 1]["start_seconds"]
            if end_index + 1 < len(scenes)
            else audio_duration_seconds
        )
        duration = end_seconds - start_seconds
        word_count = len(narration.split())
        if word_count > CREATIVE_PACKAGE_MAX_SCENE_WORDS:
            return (
                f"{scene.scene_id} sentence has {word_count} words; "
                f"the maximum is {CREATIVE_PACKAGE_MAX_SCENE_WORDS}."
            )
        if len(sentences) != 1 and not _is_one_word_sentence_pair(narration):
            return (
                f"{scene.scene_id} groups {len(sentences)} complete sentences; "
                "use one sentence per scene, or pair exactly two one-word sentences."
            )
        if duration <= 0:
            return (
                f"{scene.scene_id} has a non-positive hold of {duration:.3f}s; "
                "every scene must have positive duration."
            )
        if duration > maximum_duration_seconds:
            return (
                f"{scene.scene_id} sentence holds for {duration:.3f}s, above "
                f"the configured {maximum_duration_seconds:.3f}s maximum."
            )
        sentence_start_index = end_index + 1
    return (
        "The supplied scene boundaries do not map to one complete sentence per "
        "scene, or a permitted pair of one-word sentences."
    )


def _group_source_scenes(
    scenes: list[StoryboardScene],
    scene_matches: list[dict[str, float]],
    audio_duration_seconds: float,
    *,
    maximum_duration_seconds: float,
    target_duration_seconds: float,
) -> list[tuple[StoryboardScene, str]]:
    if len(scenes) != len(scene_matches):
        raise ValueError("Source scene matches do not cover the complete storyboard.")

    count = len(scenes)
    best: list[
        tuple[
            tuple[float, int],
            list[tuple[int, int, str]],
        ]
        | None
    ] = [None] * (count + 1)
    best[count] = ((0.0, 0), [])

    for start_index in range(count - 1, -1, -1):
        start_seconds = (
            0.0
            if start_index == 0
            else scene_matches[start_index]["start_seconds"]
        )
        for end_index in range(start_index, count):
            end_seconds = (
                scene_matches[end_index + 1]["start_seconds"]
                if end_index + 1 < count
                else audio_duration_seconds
            )
            duration = end_seconds - start_seconds
            if duration <= 0:
                continue
            if duration > maximum_duration_seconds:
                break
            suffix = best[end_index + 1]
            if suffix is None:
                continue

            boundary = (
                _scene_ending_boundary(scenes[end_index].narration)
                if end_index + 1 < count
                else "sentence"
            )
            if boundary != "sentence":
                continue

            narration = " ".join(
                scene.narration.strip()
                for scene in scenes[start_index : end_index + 1]
            )
            sentence_count = len(split_narration_sentences(narration))
            short_sentence_pair = _is_one_word_sentence_pair(narration)
            if sentence_count != 1 and not short_sentence_pair:
                continue
            if len(narration.split()) > CREATIVE_PACKAGE_MAX_SCENE_WORDS:
                continue

            suffix_cost, suffix_groups = suffix
            cost = (
                suffix_cost[0] + abs(duration - target_duration_seconds),
                suffix_cost[1] + 1,
            )
            current = best[start_index]
            if current is None or cost < current[0]:
                best[start_index] = (
                    cost,
                    [(start_index, end_index, boundary), *suffix_groups],
                )

    result = best[0]
    if result is None:
            detail = _first_grouping_failure(
                scenes,
                scene_matches,
                audio_duration_seconds,
                maximum_duration_seconds=maximum_duration_seconds,
            )
            raise ValueError(
                "Could not map the supplied storyboard to one sentence per visual "
                "scene (except a pair of one-word sentences) "
                f"with positive holds no longer than "
                f"{maximum_duration_seconds:.3f}s. {detail} Revise the storyboard "
                "so every scene ends at a complete sentence boundary."
            )

    grouped_scenes: list[tuple[StoryboardScene, str]] = []
    for start_index, end_index, boundary in result[1]:
        narration = " ".join(
            scene.narration.strip()
            for scene in scenes[start_index : end_index + 1]
        )
        representative_scene = scenes[start_index].model_copy(
            update={"narration": narration}
        )
        grouped_scenes.append((representative_scene, boundary))
    return grouped_scenes


def _apply_creative_package_scene_timing_policy(
    project_directory: Path,
    production_config: ProductionConfig,
) -> ProductionConfig:
    source_file = project_directory / "topic_selection.json"
    if not source_file.is_file():
        return production_config
    source = json.loads(source_file.read_text(encoding="utf-8"))
    if not isinstance(source, dict):
        raise TypeError("The project topic selection must contain an object.")
    if source.get("source") != "creative_package":
        return production_config
    if (
        production_config.scene_minimum_duration_seconds
        == CREATIVE_PACKAGE_SCENE_MINIMUM_DURATION_SECONDS
        and production_config.scene_maximum_duration_seconds
        == CREATIVE_PACKAGE_SCENE_MAXIMUM_DURATION_SECONDS
    ):
        return production_config

    updated_config = production_config.model_copy(
        update={
            "scene_minimum_duration_seconds": (
                CREATIVE_PACKAGE_SCENE_MINIMUM_DURATION_SECONDS
            ),
            "scene_maximum_duration_seconds": (
                CREATIVE_PACKAGE_SCENE_MAXIMUM_DURATION_SECONDS
            )
        }
    )
    config_file = project_directory / "production_config.json"
    if config_file.is_file():
        config_file.write_text(
            updated_config.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    print(
        "Set supplied creative package scene holds to any positive duration "
        f"up to {CREATIVE_PACKAGE_SCENE_MAXIMUM_DURATION_SECONDS:.3f}s."
    )
    return updated_config


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
    production_config = _apply_creative_package_scene_timing_policy(
        project_directory,
        production_config,
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
        manifest_image_path = asset.get("file_path")
        if (
            asset.get("status") != "completed"
            or asset.get("provider") != "flow_mcp"
            or not isinstance(manifest_image_path, str)
            or Path(manifest_image_path).resolve() != image_path.resolve()
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
        target_scene_duration_seconds=TARGET_SCENE_DURATION_SECONDS,
    )
    synchronization_engine = VideoSynchronizationEngine()
    matches = synchronization_engine._match_scene_narration(
        source_storyboard,
        alignment,
    )
    grouped_scenes = _group_source_scenes(
        source_scenes,
        matches,
        alignment.audio_duration_seconds,
        maximum_duration_seconds=production_config.scene_maximum_duration_seconds,
        target_duration_seconds=TARGET_SCENE_DURATION_SECONDS,
    )
    grouped_storyboard = source_storyboard.model_copy(
        update={"scenes": [scene for scene, _ in grouped_scenes]}
    )
    grouped_matches = synchronization_engine._match_scene_narration(
        grouped_storyboard,
        alignment,
    )
    timed_scenes: list[StoryboardScene] = []
    for index, ((scene, _), match) in enumerate(
        zip(grouped_scenes, grouped_matches, strict=True)
    ):
        start = 0.0 if index == 0 else match["start_seconds"]
        end = (
            grouped_matches[index + 1]["start_seconds"]
            if index + 1 < len(grouped_matches)
            else alignment.audio_duration_seconds
        )
        duration = end - start
        if duration <= 0:
            raise ValueError(
                f"{scene.scene_id} has a non-positive hold of {duration:.3f}s; "
                "every scene must have positive duration."
            )
        maximum_overage = (
            duration - production_config.scene_maximum_duration_seconds
        )
        if maximum_overage > 0:
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
                        grouped_scenes[index - 1][0].narration if index else ""
                    ),
                    "next_sentence": (
                        grouped_scenes[index + 1][0].narration
                        if index + 1 < len(grouped_scenes)
                        else ""
                    ),
                    "timing_boundary": (
                        "audio_start"
                        if index == 0
                        else grouped_scenes[index - 1][1]
                    ),
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
        target_scene_duration_seconds=TARGET_SCENE_DURATION_SECONDS,
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
