"""Build visual scene boundaries from narration alignment and story beats."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from modules.image.prompt_builder import ImagePromptBuilder
from modules.project.config import ProductionConfig
from modules.storyboard.dynamic_engine import DynamicStoryboardEngine
from modules.storyboard.editorial_qa import review_editorial_callouts
from modules.storyboard.models import Storyboard, StoryboardScene, TimingBoundary
from modules.video.sync_engine import VideoSynchronizationEngine
from modules.video.sync_models import NarrationAlignment


@dataclass(frozen=True)
class _AlignedScene:
    scene: StoryboardScene
    start_seconds: float
    end_seconds: float
    boundary_before: TimingBoundary = "audio_start"


class AudioTimedStoryboardEngine:
    """Group visual ideas at natural narration boundaries and timestamp from audio."""

    MIN_VISUAL_HOLD_SECONDS = 2.0
    PREFERRED_VISUAL_HOLD_SECONDS = 2.8
    MIN_SAFE_SCENE_DURATION_SECONDS = 1.8
    STRONG_NARRATION_PAUSE_SECONDS = 0.35
    MAX_VISUAL_HOLD_SECONDS = 4.0
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
            min(self.MIN_VISUAL_HOLD_SECONDS, config.scene_minimum_duration_seconds),
        )
        self.maximum_visual_hold_seconds = min(
            self.MAX_VISUAL_HOLD_SECONDS,
            config.scene_maximum_duration_seconds,
        )

    def build(self, storyboard: Storyboard, alignment: NarrationAlignment) -> Storyboard:
        if not storyboard.scenes:
            raise ValueError("Cannot time an empty storyboard.")
        timing_matches = VideoSynchronizationEngine()._match_scene_narration(storyboard, alignment)
        VideoSynchronizationEngine._validate_alignment(alignment)
        aligned = [
            _AlignedScene(scene=scene, start_seconds=match["start_seconds"],
                          end_seconds=match["end_seconds"],
                          boundary_before=self._boundary_before(
                              storyboard.scenes[index - 1] if index else None,
                              match["start_seconds"],
                              timing_matches[index - 1]["end_seconds"] if index else 0.0,
                          ))
            for index, (scene, match) in enumerate(
                zip(storyboard.scenes, timing_matches)
            )
        ]
        aligned = self._expand_to_aligned_words(
            aligned,
            alignment,
        )
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
                    f"Audio-timed scene {index + 1} lasts {duration:.3f}s, "
                    f"exceeding the configured maximum hold of "
                    f"{self.maximum_visual_hold_seconds:.3f}s."
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
            target_scene_duration_seconds=self.PREFERRED_VISUAL_HOLD_SECONDS,
        )
        self._validate_timeline(result, total_duration)
        return result

    @staticmethod
    def save_storyboard(storyboard: Storyboard, output_file: str | Path) -> Path:
        path = Path(output_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        from modules.qa.engine import record_stage_qa

        project_directory = path.parent.parent if path.parent.name == "storyboard" else path.parent
        initial_qa = AudioTimedStoryboardEngine._evaluate_storyboard(storyboard)
        if initial_qa.status != "PASS":
            record_stage_qa(project_directory, initial_qa)

        repaired = AudioTimedStoryboardEngine._repair_storyboard(storyboard)
        final_qa = AudioTimedStoryboardEngine._evaluate_storyboard(repaired)
        path.write_text(repaired.model_dump_json(indent=2), encoding="utf-8")
        record_stage_qa(project_directory, final_qa)
        if final_qa.status == "FAIL":
            raise ValueError(
                "Storyboard QA remains unresolved after automatic correction; "
                "inspect qa/qa_report.json before image generation."
            )
        return path

    @staticmethod
    def _evaluate_storyboard(storyboard: Storyboard):
        from modules.qa.models import QAStageResult

        try:
            AudioTimedStoryboardEngine._validate_timeline(
                storyboard,
                storyboard.total_scene_duration_seconds,
            )
            timeline_valid = True
        except ValueError:
            timeline_valid = False

        prompts_valid = bool(storyboard.scenes) and all(
            scene.image_prompt.strip() for scene in storyboard.scenes
        )
        static_camera = all(
            scene.camera_motion == "static" for scene in storyboard.scenes
        )
        hard_cuts = all(scene.transition == "cut" for scene in storyboard.scenes)
        editorial_qa = review_editorial_callouts(storyboard.scenes)
        maximum_duration_valid = all(
            scene.duration_seconds <= AudioTimedStoryboardEngine.MAX_VISUAL_HOLD_SECONDS
            for scene in storyboard.scenes
        )
        preferred_pacing = all(
            scene.duration_seconds >= AudioTimedStoryboardEngine.MIN_SAFE_SCENE_DURATION_SECONDS
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
        if not maximum_duration_valid:
            findings.append("One or more scenes exceed the 4-second visual hold maximum.")
        if not preferred_pacing:
            findings.append("One or more scenes are shorter than the preferred 2-second minimum.")
        if any(scene.timing_boundary == "word_fallback" for scene in storyboard.scenes[1:]):
            findings.append(
                "One or more cuts use a word boundary because no natural clause or pause "
                "boundary was available; review those cuts."
            )
        findings.extend(editorial_qa.findings)
        hard_checks_pass = (
            timeline_valid
            and prompts_valid
            and static_camera
            and hard_cuts
            and maximum_duration_valid
        )
        status = (
            "FAIL"
            if not hard_checks_pass
            else "REVIEW"
            if editorial_qa.status == "REVIEW" or not preferred_pacing
            or any(scene.timing_boundary == "word_fallback" for scene in storyboard.scenes[1:])
            else "PASS"
        )
        return QAStageResult(
            stage="storyboard",
            status=status,
            checks={
                "timeline_coverage": "PASS" if timeline_valid else "FAIL",
                "scene_prompts": "PASS" if prompts_valid else "FAIL",
                "static_camera": "PASS" if static_camera else "FAIL",
                "hard_cuts": "PASS" if hard_cuts else "FAIL",
                "maximum_scene_duration": "PASS" if maximum_duration_valid else "FAIL",
                "preferred_scene_pacing": "PASS" if preferred_pacing else "REVIEW",
                "natural_cut_boundaries": (
                    "REVIEW"
                    if any(scene.timing_boundary == "word_fallback" for scene in storyboard.scenes[1:])
                    else "PASS"
                ),
                "editorial_callouts": editorial_qa.status,
                "editorial_format": (
                    "REVIEW" if editorial_qa.malformed_callouts else "PASS"
                ),
            },
            findings=findings,
            recommendations=(
                ["Applying safe storyboard corrections."]
                if findings
                else []
            ),
            metrics=editorial_qa.metrics(),
            details=editorial_qa.scene_statuses,
        )

    @staticmethod
    def _repair_storyboard(storyboard: Storyboard) -> Storyboard:
        scenes = [
            scene.model_copy(
                update={
                    "camera_motion": "static",
                    "transition": "cut",
                }
            )
            for scene in storyboard.scenes
        ]
        prompt_builder = ImagePromptBuilder()
        scenes = [
            scene.model_copy(
                update={"image_prompt": prompt_builder.build(scene)}
            )
            if not scene.image_prompt.strip()
            else scene
            for scene in scenes
        ]

        previous_end = 0.0
        timeline_valid = True
        for index, scene in enumerate(scenes):
            if index and abs(scene.start_seconds - previous_end) > 0.01:
                timeline_valid = False
            previous_end = scene.start_seconds + scene.duration_seconds
        if abs(previous_end - storyboard.total_scene_duration_seconds) > 0.01:
            timeline_valid = False
        if not timeline_valid and scenes:
            total_duration = storyboard.total_scene_duration_seconds
            final_duration = total_duration - sum(
                scene.duration_seconds for scene in scenes[:-1]
            )
            if 0 < final_duration <= 30:
                repaired_scenes = []
                next_start = 0.0
                for index, scene in enumerate(scenes):
                    duration = (
                        final_duration
                        if index == len(scenes) - 1
                        else scene.duration_seconds
                    )
                    repaired_scenes.append(
                        scene.model_copy(
                            update={
                                "start_seconds": next_start,
                                "duration_seconds": duration,
                            }
                        )
                    )
                    next_start += duration
                scenes = repaired_scenes

        if review_editorial_callouts(scenes).status == "REVIEW":
            scenes = DynamicStoryboardEngine().apply_production_editorial_callouts(
                scenes
            )
        return storyboard.model_copy(update={"scenes": scenes})

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
                natural_boundary = item.boundary_before in {
                    "sentence",
                    "clause",
                    "pause",
                } or pause >= self.STRONG_NARRATION_PAUSE_SECONDS
                visual_change = (
                    not self._same_visual_idea(previous.scene, item.scene)
                    or item.boundary_before == "clause"
                )
                safe_duration = (
                    elapsed >= self.MIN_SAFE_SCENE_DURATION_SECONDS
                )
                maximum_reached = (
                    next_start - current[0].start_seconds
                    >= self.maximum_visual_hold_seconds
                )
                if (
                    safe_duration
                    and (
                        maximum_reached
                        or (natural_boundary and visual_change)
                    )
                ):
                    groups.append(current)
                    current = []
            current.append(item)
        if current:
            groups.append(current)
        if len(groups) > 1:
            trailing_duration = audio_duration - groups[-1][0].start_seconds
            merged_duration = (
                audio_duration - groups[-2][0].start_seconds
            )
            if trailing_duration < self.MIN_SAFE_SCENE_DURATION_SECONDS:
                if merged_duration <= self.maximum_visual_hold_seconds:
                    groups[-2].extend(groups[-1])
                    groups.pop()
                else:
                    previous_group = groups[-2]
                    target_start = (
                        audio_duration - self.PREFERRED_VISUAL_HOLD_SECONDS
                    )
                    eligible_splits = [
                        split_index
                        for split_index in range(1, len(previous_group))
                        if (
                            self.MIN_SAFE_SCENE_DURATION_SECONDS
                            <= previous_group[split_index].start_seconds
                            - previous_group[0].start_seconds
                            <= self.maximum_visual_hold_seconds
                        )
                    ]
                    if eligible_splits:
                        split_index = min(
                            eligible_splits,
                            key=lambda candidate: abs(
                                previous_group[candidate].start_seconds
                                - target_start
                            ),
                        )
                        groups[-1] = (
                            previous_group[split_index:] + groups[-1]
                        )
                        groups[-2] = previous_group[:split_index]
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
            and (
                self._same_visual_idea(previous_scene, first)
                or self._same_composition(previous_scene, first)
            )
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
            props=props, text_overlay=editorial,
            timing_boundary=group[0].boundary_before,
            camera_motion="static", transition="cut",
            research_sources=sources, image_prompt="audio-timed placeholder",
        )
        merged.image_prompt = self.prompt_builder.build(merged)
        return merged

    @staticmethod
    def _ends_sentence(narration: str) -> bool:
        return bool(re.search(r"""[.!?]["')\]]*$""", narration.strip()))

    @classmethod
    def _boundary_before(
        cls,
        previous_scene: StoryboardScene | None,
        start_seconds: float,
        previous_end_seconds: float,
    ) -> TimingBoundary:
        if previous_scene is None:
            return "audio_start"
        if cls._ends_sentence(previous_scene.narration):
            return "sentence"
        if start_seconds - previous_end_seconds >= cls.STRONG_NARRATION_PAUSE_SECONDS:
            return "pause"
        return "clause"

    def _expand_to_aligned_words(
        self,
        aligned: list[_AlignedScene],
        alignment: NarrationAlignment,
    ) -> list[_AlignedScene]:
        compact_script, original_indices = (
            VideoSynchronizationEngine._build_compact_mapping(alignment.characters)
        )
        result: list[_AlignedScene] = []
        search_cursor = 0
        for item in aligned:
            compact_narration = VideoSynchronizationEngine._compact_text(
                item.scene.narration
            )
            match_start = compact_script.find(compact_narration, search_cursor)
            if match_start < 0:
                raise ValueError(
                    f"Could not recover word timing for {item.scene.scene_id}."
                )
            search_cursor = match_start + len(compact_narration)
            words = [
                match
                for match in re.finditer(r"\S+", item.scene.narration)
                if VideoSynchronizationEngine._compact_text(match.group())
            ]
            previous_word = ""
            previous_end_seconds = item.start_seconds
            for word_index, word in enumerate(words):
                compact_offset = len(
                    VideoSynchronizationEngine._compact_text(
                        item.scene.narration[:word.start()]
                    )
                )
                compact_word = VideoSynchronizationEngine._compact_text(word.group())
                first_compact = match_start + compact_offset
                last_compact = first_compact + len(compact_word) - 1
                first_original = original_indices[first_compact]
                last_original = original_indices[last_compact]
                word_start = alignment.character_start_times_seconds[first_original]
                word_end = alignment.character_end_times_seconds[last_original]
                boundary: TimingBoundary = (
                    item.boundary_before
                    if word_index == 0
                    else self._word_boundary_before(
                        previous_word,
                        word.group(),
                        word_start - previous_end_seconds,
                    )
                )
                result.append(
                    _AlignedScene(
                        scene=item.scene.model_copy(
                            update={
                                "narration": word.group(),
                                "timing_boundary": boundary,
                            }
                        ),
                        start_seconds=word_start,
                        end_seconds=word_end,
                        boundary_before=boundary,
                    )
                )
                previous_word = word.group()
                previous_end_seconds = word_end
        return result

    @classmethod
    def _word_boundary_before(
        cls,
        previous_word: str,
        current_word: str,
        pause_seconds: float,
    ) -> TimingBoundary:
        if cls._ends_sentence(previous_word):
            return "sentence"
        if re.search(r"[,;:—]$", previous_word):
            return "clause"
        if re.match(
            r"^(?:and|but|because|while|although|whereas|which|so|when|before|after)\b",
            current_word,
            re.IGNORECASE,
        ):
            return "clause"
        if pause_seconds >= cls.STRONG_NARRATION_PAUSE_SECONDS:
            return "pause"
        return "word_fallback"

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
            if scene.duration_seconds > AudioTimedStoryboardEngine.MAX_VISUAL_HOLD_SECONDS:
                raise ValueError(
                    f"{scene.scene_id} lasts {scene.duration_seconds:.3f}s, "
                    "exceeding the 4-second visual hold maximum."
                )
            if index and abs(scene.start_seconds - previous_end) > 0.01:
                raise ValueError(f"{scene.scene_id} is not continuous with the previous scene.")
            previous_end = scene.start_seconds + scene.duration_seconds
        if abs(previous_end - audio_duration) > 0.01:
            raise ValueError("Audio-timed storyboard does not cover the full narration.")
