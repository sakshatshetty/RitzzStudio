"""Build visual scene boundaries from narration alignment and story beats."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from modules.image.prompt_builder import ImagePromptBuilder
from modules.project.config import ProductionConfig
from modules.storyboard.dynamic_engine import DynamicStoryboardEngine
from modules.storyboard.editorial_qa import review_editorial_callouts
from modules.storyboard.models import Storyboard, StoryboardScene
from modules.video.sync_engine import VideoSynchronizationEngine
from modules.video.sync_models import NarrationAlignment


@dataclass(frozen=True)
class _AlignedScene:
    scene: StoryboardScene
    start_seconds: float
    end_seconds: float


class AudioTimedStoryboardEngine:
    """Group visual ideas at natural narration boundaries and timestamp from audio."""

    MIN_VISUAL_HOLD_SECONDS = 1.8
    MIN_SAFE_SCENE_DURATION_SECONDS = 1.5
    STRONG_NARRATION_PAUSE_SECONDS = 0.45
    FOCUS_MARKER = "Focus specifically on this visual beat:"
    NARRATION_DESCRIPTION_MARKER = "The character should visually represent this narration:"
    STOP_WORDS: ClassVar[set[str]] = {
        "a", "about", "again", "all", "an", "and", "are", "as", "at",
        "be", "because", "been", "before", "being", "but", "by", "can",
        "did", "do", "does", "down", "each", "for", "from", "had", "has",
        "have", "he", "her", "here", "him", "his", "how", "i", "if", "in",
        "into", "is", "it", "its", "just", "more", "most", "not", "of",
        "on", "once", "or", "our", "out", "over", "she", "so", "some",
        "than", "that", "the", "their", "them", "then", "there", "these",
        "they", "this", "those", "through", "to", "under", "up", "was",
        "were", "what", "when", "where", "which", "who", "why", "will",
        "with", "would", "you", "your",
    }
    WORD_NORMALIZATIONS: ClassVar[dict[str, str]] = {
        "built": "build",
        "cities": "city",
        "rebuilt": "build",
        "rebuilding": "build",
    }

    def __init__(self, prompt_builder: ImagePromptBuilder | None = None,
                 production_config: ProductionConfig | None = None) -> None:
        self.prompt_builder = prompt_builder or ImagePromptBuilder()
        config = production_config or ProductionConfig()
        self.minimum_visual_hold_seconds = max(
            self.MIN_SAFE_SCENE_DURATION_SECONDS,
            config.scene_minimum_duration_seconds,
        )
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
            scenes.append(
                self._merge_group(
                    group,
                    index + 1,
                    start,
                    duration,
                    scenes[-1] if scenes else None,
                )
            )
        scenes = DynamicStoryboardEngine(
            prompt_builder=self.prompt_builder,
        ).apply_production_editorial_callouts(scenes)
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
        editorial_qa = review_editorial_callouts(storyboard.scenes)
        findings = []
        if not timeline_valid:
            findings.append("Storyboard timing has gaps, overlaps, or incomplete coverage.")
        if not prompts_valid:
            findings.append("One or more scenes have no production image prompt.")
        if not static_camera:
            findings.append("One or more production scenes are not static-camera.")
        if not hard_cuts:
            findings.append("One or more production scenes do not use hard cuts.")
        findings.extend(editorial_qa.findings)

        from modules.qa.engine import record_stage_qa
        from modules.qa.models import QAStageResult

        project_directory = path.parent.parent if path.parent.name == "storyboard" else path.parent
        hard_checks_pass = timeline_valid and prompts_valid and static_camera and hard_cuts
        record_stage_qa(
            project_directory,
            QAStageResult(
                stage="storyboard",
                status=(
                    "FAIL"
                    if not hard_checks_pass
                    else "REVIEW"
                    if editorial_qa.status == "REVIEW"
                    else "PASS"
                ),
                checks={
                    "timeline_coverage": "PASS" if timeline_valid else "FAIL",
                    "scene_prompts": "PASS" if prompts_valid else "FAIL",
                    "static_camera": "PASS" if static_camera else "FAIL",
                    "hard_cuts": "PASS" if hard_cuts else "FAIL",
                    "editorial_callouts": editorial_qa.status,
                    "editorial_format": (
                        "REVIEW" if editorial_qa.malformed_callouts else "PASS"
                    ),
                },
                findings=findings,
                recommendations=["Correct the flagged storyboard scenes before image generation."] if findings else [],
                metrics=editorial_qa.metrics(),
                details=editorial_qa.scene_statuses,
            ),
        )
        return path

    def _group_short_beats(self, aligned: list[_AlignedScene], audio_duration: float) -> list[list[_AlignedScene]]:
        groups: list[list[_AlignedScene]] = []
        current: list[_AlignedScene] = []
        for index, item in enumerate(aligned):
            if current:
                previous = current[-1]
                elapsed = item.start_seconds - current[0].start_seconds
                next_start = (
                    aligned[index + 1].start_seconds
                    if index + 1 < len(aligned)
                    else audio_duration
                )
                pause = max(0.0, item.start_seconds - previous.end_seconds)
                natural_boundary = (
                    self._ends_sentence(previous.scene.narration)
                    or pause >= self.STRONG_NARRATION_PAUSE_SECONDS
                )
                visual_change = not self._same_visual_idea(
                    previous.scene,
                    item.scene,
                )
                safe_duration = (
                    elapsed >= self.MIN_SAFE_SCENE_DURATION_SECONDS
                )
                maximum_reached = (
                    next_start - current[0].start_seconds
                    >= self.maximum_visual_hold_seconds
                )
                if (
                    natural_boundary
                    and safe_duration
                    and (visual_change or maximum_reached)
                ):
                    groups.append(current)
                    current = []
            current.append(item)
        if current:
            groups.append(current)
        if (
            len(groups) > 1
            and audio_duration - groups[-1][0].start_seconds
            < self.MIN_SAFE_SCENE_DURATION_SECONDS
        ):
            groups[-2].extend(groups[-1])
            groups.pop()
        return groups

    def _merge_group(self, group: list[_AlignedScene], number: int,
                     start_seconds: float, duration_seconds: float,
                     previous_scene: StoryboardScene | None = None) -> StoryboardScene:
        first = group[0].scene
        narration = " ".join(item.scene.narration.strip() for item in group).strip()
        description = self._base_visual_description(first)
        if not description:
            description = first.visual_description.strip()
        variation = ""
        if (
            previous_scene is not None
            and not self._same_visual_idea(previous_scene, first)
            and self._same_composition(previous_scene, first)
        ):
            variation = (
                " Advance to a distinct visual beat with a meaningfully different "
                "composition, viewpoint, action, scale, or evidence detail; do not "
                "repeat the preceding composition."
            )
        visual_description = (
            f"{description}{variation} {self.FOCUS_MARKER} {narration}"
        )
        props = list(dict.fromkeys(prop for item in group for prop in item.scene.props))[:3]
        sources = list(dict.fromkeys(source for item in group for source in item.scene.research_sources))
        action = next(
            (
                item.scene.character_action
                for item in reversed(group)
                if item.scene.character_action.strip()
            ),
            first.character_action,
        )
        background = next(
            (
                item.scene.background
                for item in reversed(group)
                if item.scene.background.strip()
            ),
            first.background,
        )
        editorial = next(
            (item.scene.text_overlay for item in group if item.scene.text_overlay.strip()),
            "",
        )
        merged = StoryboardScene(
            scene_id=f"scene_{number:03d}", section_id=first.section_id,
            start_seconds=start_seconds, duration_seconds=duration_seconds,
            narration=narration, visual_style=first.visual_style,
            visual_description=visual_description,
            character_action=action, background=background,
            props=props, text_overlay=editorial, camera_motion="static", transition="cut",
            research_sources=sources, image_prompt="audio-timed placeholder",
        )
        merged.image_prompt = self.prompt_builder.build(merged)
        return merged

    @staticmethod
    def _ends_sentence(narration: str) -> bool:
        return bool(re.search(r"""[.!?]["')\]]*$""", narration.strip()))

    @classmethod
    def _concept_tokens(cls, scene: StoryboardScene) -> set[str]:
        description = scene.visual_description.split(cls.FOCUS_MARKER, 1)[0]
        if (
            cls.NARRATION_DESCRIPTION_MARKER in description
            or "Simple hand-drawn stick-man explainer scene" in description
        ):
            description = ""
        tokens = re.findall(
            r"[a-z0-9]+",
            f"{scene.narration} {description} {' '.join(scene.props)}".lower(),
        )
        normalized: set[str] = set()
        for token in tokens:
            if token in cls.STOP_WORDS:
                continue
            normalized.add(
                cls.WORD_NORMALIZATIONS.get(token, token) or token
            )
        return normalized

    @classmethod
    def _same_visual_idea(
        cls,
        previous: StoryboardScene,
        current: StoryboardScene,
    ) -> bool:
        previous_description = cls._base_visual_description(previous).casefold()
        current_description = cls._base_visual_description(current).casefold()
        if previous_description and previous_description == current_description:
            return True

        previous_tokens = cls._concept_tokens(previous)
        current_tokens = cls._concept_tokens(current)
        if not previous_tokens or not current_tokens:
            return False
        shared = previous_tokens & current_tokens
        if not shared:
            return False

        overlap = len(shared) / min(len(previous_tokens), len(current_tokens))
        return len(shared) >= 2 or overlap >= 0.5

    @classmethod
    def _base_visual_description(cls, scene: StoryboardScene) -> str:
        description = scene.visual_description.split(cls.FOCUS_MARKER, 1)[0]
        if cls.NARRATION_DESCRIPTION_MARKER in description:
            return ""
        if "Simple hand-drawn stick-man explainer scene" in description:
            return ""
        return description.strip()

    @staticmethod
    def _same_composition(previous: StoryboardScene, current: StoryboardScene) -> bool:
        return (
            previous.character_action.strip().casefold()
            == current.character_action.strip().casefold()
            and previous.background.strip().casefold()
            == current.background.strip().casefold()
            and [prop.casefold() for prop in previous.props]
            == [prop.casefold() for prop in current.props]
        )

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
