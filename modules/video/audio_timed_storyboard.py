"""Build visual scene boundaries from narration alignment and story beats."""

from dataclasses import dataclass
from pathlib import Path

from modules.image.prompt_builder import ImagePromptBuilder
from modules.project.config import ProductionConfig
from modules.storyboard.models import Storyboard, StoryboardScene
from modules.video.sync_engine import VideoSynchronizationEngine
from modules.video.sync_models import NarrationAlignment


@dataclass(frozen=True)
class _AlignedScene:
    scene: StoryboardScene
    start_seconds: float
    end_seconds: float


class AudioTimedStoryboardEngine:
    """Coalesce short storyboard beats and timestamp scenes from actual audio."""

    MIN_VISUAL_HOLD_SECONDS = 3.0
    FOCUS_MARKER = "Focus specifically on this visual beat:"

    def __init__(self, prompt_builder: ImagePromptBuilder | None = None,
                 production_config: ProductionConfig | None = None) -> None:
        self.prompt_builder = prompt_builder or ImagePromptBuilder()
        config = production_config or ProductionConfig()
        self.minimum_visual_hold_seconds = config.scene_minimum_duration_seconds
        self.maximum_visual_hold_seconds = config.scene_maximum_duration_seconds

    def build(self, storyboard: Storyboard, alignment: NarrationAlignment) -> Storyboard:
        if not storyboard.scenes:
            raise ValueError("Cannot time an empty storyboard.")
        timing_matches = VideoSynchronizationEngine()._match_scene_narration(storyboard, alignment)
        VideoSynchronizationEngine._validate_alignment(alignment)
        aligned = [
            _AlignedScene(scene=scene, start_seconds=match["start_seconds"],
                          end_seconds=match["end_seconds"])
            for scene, match in zip(storyboard.scenes, timing_matches)
        ]
        groups = self._group_short_beats(aligned, alignment.audio_duration_seconds)
        scenes: list[StoryboardScene] = []
        for index, group in enumerate(groups):
            start = 0.0 if index == 0 else group[0].start_seconds
            end = groups[index + 1][0].start_seconds if index + 1 < len(groups) else alignment.audio_duration_seconds
            duration = end - start
            if duration <= 0:
                raise ValueError(f"Audio-timed scene {index + 1} has non-positive duration.")
            if duration > self.maximum_visual_hold_seconds:
                raise ValueError(
                    f"Audio-timed scene {index + 1} exceeds the configured maximum hold."
                )
            scenes.append(self._merge_group(group, index + 1, start, duration))
        total_duration = alignment.audio_duration_seconds
        result = Storyboard(
            topic=storyboard.topic,
            target_duration_seconds=round(total_duration),
            scenes=scenes,
            total_scene_duration_seconds=total_duration,
            target_scene_duration_seconds=self.minimum_visual_hold_seconds,
        )
        self._validate_timeline(result, total_duration)
        return result

    @staticmethod
    def save_storyboard(storyboard: Storyboard, output_file: str | Path) -> Path:
        path = Path(output_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(storyboard.model_dump_json(indent=2), encoding="utf-8")

        timeline_valid = True
        try:
            AudioTimedStoryboardEngine._validate_timeline(
                storyboard,
                storyboard.total_scene_duration_seconds,
            )
        except ValueError:
            timeline_valid = False

        prompts_valid = bool(storyboard.scenes) and all(
            scene.image_prompt.strip() for scene in storyboard.scenes
        )
        static_camera = all(scene.camera_motion == "static" for scene in storyboard.scenes)
        hard_cuts = all(scene.transition == "cut" for scene in storyboard.scenes)
        editorial_valid = all(
            not scene.text_overlay
            or (
                len(scene.text_overlay.split()) == 1
                and scene.text_overlay.isupper()
                and len(scene.text_overlay) <= 20
            )
            for scene in storyboard.scenes
        )
        findings = []
        if not timeline_valid:
            findings.append("Storyboard timing has gaps, overlaps, or incomplete coverage.")
        if not prompts_valid:
            findings.append("One or more scenes have no production image prompt.")
        if not static_camera:
            findings.append("One or more production scenes are not static-camera.")
        if not hard_cuts:
            findings.append("One or more production scenes do not use hard cuts.")
        if not editorial_valid:
            findings.append("One or more editorial callouts are not a single uppercase word of at most 20 characters.")

        from modules.qa.engine import record_stage_qa
        from modules.qa.models import QAStageResult

        project_directory = path.parent.parent if path.parent.name == "storyboard" else path.parent
        hard_checks_pass = timeline_valid and prompts_valid and static_camera and hard_cuts
        record_stage_qa(
            project_directory,
            QAStageResult(
                stage="storyboard",
                status="FAIL" if not hard_checks_pass else "REVIEW" if not editorial_valid else "PASS",
                checks={
                    "timeline_coverage": "PASS" if timeline_valid else "FAIL",
                    "scene_prompts": "PASS" if prompts_valid else "FAIL",
                    "static_camera": "PASS" if static_camera else "FAIL",
                    "hard_cuts": "PASS" if hard_cuts else "FAIL",
                    "editorial_format": "PASS" if editorial_valid else "REVIEW",
                },
                findings=findings,
                recommendations=["Correct the flagged storyboard scenes before image generation."] if findings else [],
            ),
        )
        return path

    def _group_short_beats(self, aligned: list[_AlignedScene], audio_duration: float) -> list[list[_AlignedScene]]:
        groups: list[list[_AlignedScene]] = []
        current: list[_AlignedScene] = []
        current_start = 0.0
        for item in aligned:
            elapsed = item.start_seconds - current_start if current else 0.0
            hold_reached = bool(current) and elapsed >= self.minimum_visual_hold_seconds
            if hold_reached:
                groups.append(current)
                current = []
            if not current:
                current_start = item.start_seconds
            current.append(item)
        if current:
            groups.append(current)
        if len(groups) > 1 and audio_duration - groups[-1][0].start_seconds < self.minimum_visual_hold_seconds:
            groups[-2].extend(groups[-1])
            groups.pop()
        return groups

    def _merge_group(self, group: list[_AlignedScene], number: int,
                     start_seconds: float, duration_seconds: float) -> StoryboardScene:
        first = group[0].scene
        narration = " ".join(item.scene.narration.strip() for item in group).strip()
        focus = narration
        descriptions = []
        for item in group:
            description = item.scene.visual_description.strip()
            if self.FOCUS_MARKER in description:
                description = description.split(self.FOCUS_MARKER, 1)[0].strip()
            if description not in descriptions:
                descriptions.append(description)
        description = " ; ".join(descriptions)
        visual_description = f"{description} {self.FOCUS_MARKER} {focus}"
        props = list(dict.fromkeys(prop for item in group for prop in item.scene.props))
        sources = list(dict.fromkeys(source for item in group for source in item.scene.research_sources))
        editorial = next((item.scene.text_overlay for item in group if item.scene.text_overlay.strip()), "")
        merged = StoryboardScene(
            scene_id=f"scene_{number:03d}", section_id=first.section_id,
            start_seconds=start_seconds, duration_seconds=duration_seconds,
            narration=narration, visual_style=first.visual_style,
            visual_description=visual_description,
            character_action=first.character_action, background=first.background,
            props=props, text_overlay=editorial, camera_motion="static", transition="cut",
            research_sources=sources, image_prompt="audio-timed placeholder",
        )
        merged.image_prompt = self.prompt_builder.build(merged)
        return merged

    @staticmethod
    def _validate_timeline(storyboard: Storyboard, audio_duration: float) -> None:
        previous_end = 0.0
        for index, scene in enumerate(storyboard.scenes):
            if scene.start_seconds < 0 or scene.duration_seconds <= 0:
                raise ValueError(f"{scene.scene_id} has invalid timing.")
            if index and abs(scene.start_seconds - previous_end) > 0.01:
                raise ValueError(f"{scene.scene_id} is not continuous with the previous scene.")
            previous_end = scene.start_seconds + scene.duration_seconds
        if abs(previous_end - audio_duration) > 0.01:
            raise ValueError("Audio-timed storyboard does not cover the full narration.")
