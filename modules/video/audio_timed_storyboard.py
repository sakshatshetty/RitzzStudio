"""Build visual scene boundaries from narration alignment and story beats."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from modules.image.prompt_builder import ImagePromptBuilder
from modules.project.config import ProductionConfig
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

    MIN_VISUAL_HOLD_SECONDS = ProductionConfig().scene_minimum_duration_seconds
    PREFERRED_VISUAL_HOLD_SECONDS = (
        ProductionConfig().scene_minimum_duration_seconds
        + ProductionConfig().scene_maximum_duration_seconds
    ) / 2
    MIN_SAFE_SCENE_DURATION_SECONDS = ProductionConfig().scene_minimum_duration_seconds
    STRONG_NARRATION_PAUSE_SECONDS = 0.35
    MAX_VISUAL_HOLD_SECONDS = ProductionConfig().scene_maximum_duration_seconds
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
    BOUNDARY_PRIORITY: ClassVar[dict[str, int]] = {
        "sentence": 5,
        "clause": 4,
        "pause": 3,
        "word_fallback": 1,
    }
    LONG_HOLD_REASONS: ClassVar[set[str]] = {
        "SUSTAINED_SCENE_SETTING",
        "SINGLE_VISUAL_IDEA",
        "DELIBERATE_EXPLANATION",
        "REVEAL",
    }
    SHORT_HOLD_REASONS: ClassVar[set[str]] = {
        "HIGH_INFORMATION_DENSITY",
        "RAPID_VISUAL_BEAT",
        "DISCRETE_VISUAL_BEAT",
    }

    def __init__(self, prompt_builder: ImagePromptBuilder | None = None,
                 production_config: ProductionConfig | None = None) -> None:
        self.prompt_builder = prompt_builder or ImagePromptBuilder()
        self.production_config = production_config or ProductionConfig()
        self.minimum_visual_hold_seconds = (
            self.production_config.scene_minimum_duration_seconds
        )
        self.maximum_visual_hold_seconds = (
            self.production_config.scene_maximum_duration_seconds
        )
        self.preferred_visual_hold_seconds = (
            self.minimum_visual_hold_seconds + self.maximum_visual_hold_seconds
        ) / 2

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
                              scene,
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
            if not (
                self.minimum_visual_hold_seconds
                <= duration
                <= self.maximum_visual_hold_seconds
            ):
                raise ValueError(
                    f"Audio-timed scene {index + 1} lasts {duration:.3f}s, "
                    f"outside the configured "
                    f"{self.minimum_visual_hold_seconds:.3f}–"
                    f"{self.maximum_visual_hold_seconds:.3f}s range."
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
        total_duration = alignment.audio_duration_seconds
        result = Storyboard(
            topic=storyboard.topic,
            target_duration_seconds=round(total_duration),
            scenes=scenes,
            total_scene_duration_seconds=total_duration,
            target_scene_duration_seconds=self.preferred_visual_hold_seconds,
        )
        self._validate_timeline(
            result,
            total_duration,
            self.minimum_visual_hold_seconds,
            self.maximum_visual_hold_seconds,
        )
        return result

    @staticmethod
    def save_storyboard(
        storyboard: Storyboard,
        output_file: str | Path,
        production_config: ProductionConfig | None = None,
    ) -> Path:
        path = Path(output_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        from modules.qa.engine import record_stage_qa

        project_directory = path.parent.parent if path.parent.name == "storyboard" else path.parent
        initial_qa = AudioTimedStoryboardEngine._evaluate_storyboard(
            storyboard,
            production_config,
        )
        if initial_qa.status != "PASS":
            record_stage_qa(project_directory, initial_qa)

        repaired = AudioTimedStoryboardEngine._repair_storyboard(storyboard)
        final_qa = AudioTimedStoryboardEngine._evaluate_storyboard(
            repaired,
            production_config,
        )
        path.write_text(repaired.model_dump_json(indent=2), encoding="utf-8")
        record_stage_qa(project_directory, final_qa)
        if final_qa.status == "FAIL":
            raise ValueError(
                "Storyboard QA remains unresolved after automatic correction; "
                "inspect qa/qa_report.json before image generation."
            )
        return path

    @staticmethod
    def _evaluate_storyboard(
        storyboard: Storyboard,
        production_config: ProductionConfig | None = None,
    ):
        from modules.qa.models import QAStageResult

        config = production_config or ProductionConfig()
        try:
            AudioTimedStoryboardEngine._validate_timeline(
                storyboard,
                storyboard.total_scene_duration_seconds,
                config.scene_minimum_duration_seconds,
                config.scene_maximum_duration_seconds,
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
        maximum_duration_valid = all(
            scene.duration_seconds <= config.scene_maximum_duration_seconds
            for scene in storyboard.scenes
        )
        preferred_pacing = all(
            scene.duration_seconds >= config.scene_minimum_duration_seconds
            for scene in storyboard.scenes
        )
        hold_rationale_findings = [
            f"{scene.scene_id}: {scene.duration_seconds:.3f}s hold has no "
            f"valid rationale ({scene.hold_reason or 'missing'})."
            for scene in storyboard.scenes
            if not AudioTimedStoryboardEngine._valid_hold_rationale(scene)
        ]
        hold_rationale_findings.extend(
            f"{scene.scene_id}: no natural cut boundary was found within this long hold."
            for scene in storyboard.scenes
            if scene.hold_reason == "NO_NATURAL_BOUNDARY_FOUND"
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
            findings.append("One or more scenes exceed the configured visual hold maximum.")
        if not preferred_pacing:
            findings.append("One or more scenes are shorter than the configured minimum.")
        findings.extend(hold_rationale_findings)
        if any(scene.timing_boundary == "word_fallback" for scene in storyboard.scenes[1:]):
            findings.append(
                "One or more cuts use a word boundary because no natural clause or pause "
                "boundary was available; review those cuts."
            )
        hard_checks_pass = (
            timeline_valid
            and prompts_valid
            and static_camera
            and hard_cuts
            and maximum_duration_valid
            and preferred_pacing
        )
        status = (
            "FAIL"
            if not hard_checks_pass
            else "REVIEW"
            if any(
                scene.timing_boundary == "word_fallback"
                for scene in storyboard.scenes[1:]
            ) or hold_rationale_findings
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
                "minimum_scene_duration": "PASS" if preferred_pacing else "FAIL",
                "preferred_scene_pacing": "PASS" if preferred_pacing else "FAIL",
                "variable_hold_rationale": (
                    "REVIEW" if hold_rationale_findings else "PASS"
                ),
                "natural_cut_boundaries": (
                    "REVIEW"
                    if any(scene.timing_boundary == "word_fallback" for scene in storyboard.scenes[1:])
                    else "PASS"
                ),
            },
            findings=findings,
            recommendations=(
                ["Applying safe storyboard corrections."]
                if findings
                else []
            ),
        )

    @classmethod
    def _valid_hold_rationale(cls, scene: StoryboardScene) -> bool:
        if scene.duration_seconds < 2:
            if scene.hold_reason not in cls.SHORT_HOLD_REASONS:
                return False
            if scene.hold_reason == "HIGH_INFORMATION_DENSITY":
                return scene.narration_density >= 2.5
            if scene.hold_reason == "DISCRETE_VISUAL_BEAT":
                return scene.visual_weight >= 4
            return scene.narration_density < 2.5 and scene.visual_weight < 4
        if scene.duration_seconds > 6:
            if scene.hold_reason not in cls.LONG_HOLD_REASONS:
                return False
            if scene.hold_reason == "SUSTAINED_SCENE_SETTING":
                return scene.scene_purpose == "ESTABLISH"
            if scene.hold_reason == "SINGLE_VISUAL_IDEA":
                return scene.visual_weight <= 2
            if scene.hold_reason == "REVEAL":
                return scene.scene_purpose == "REVEAL"
            return (
                scene.scene_purpose == "EXPLAIN"
                and scene.narration_density < 2.5
            )
        return True

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

        return storyboard.model_copy(update={"scenes": scenes})

    def _group_short_beats(
        self,
        aligned: list[_AlignedScene],
        audio_duration: float,
    ) -> list[list[_AlignedScene]]:
        if not aligned:
            raise ValueError("Cannot group an empty narration alignment.")
        if audio_duration < self.minimum_visual_hold_seconds:
            raise ValueError(
                f"Narration duration {audio_duration:.3f}s is shorter than the "
                f"minimum scene duration {self.minimum_visual_hold_seconds:.3f}s."
            )

        count = len(aligned)
        scores: list[float | None] = [None] * (count + 1)
        previous: list[int | None] = [None] * (count + 1)
        scores[0] = 0.0

        for start_index in range(count):
            prior_score = scores[start_index]
            if prior_score is None:
                continue
            start_seconds = (
                0.0 if start_index == 0 else aligned[start_index].start_seconds
            )
            for end_index in range(start_index + 1, count + 1):
                end_seconds = (
                    audio_duration
                    if end_index == count
                    else aligned[end_index].start_seconds
                )
                duration = end_seconds - start_seconds
                if duration > self.maximum_visual_hold_seconds:
                    break
                if duration < self.minimum_visual_hold_seconds:
                    continue

                boundary_score = 0.0
                if end_index < count:
                    next_word = aligned[end_index]
                    previous_word = aligned[end_index - 1]
                    priority = self.BOUNDARY_PRIORITY.get(
                        next_word.boundary_before,
                        0,
                    )
                    visual_change = not self._same_visual_idea(
                        previous_word.scene,
                        next_word.scene,
                    )
                    boundary_score += priority * 100
                    if visual_change:
                        boundary_score += 25
                target_hold = self._target_hold_seconds(
                    aligned[start_index:end_index],
                    duration,
                    self.minimum_visual_hold_seconds,
                    self.maximum_visual_hold_seconds,
                )
                boundary_score -= abs(duration - target_hold) * 10
                candidate_score = prior_score + boundary_score
                current_score = scores[end_index]
                if current_score is None or candidate_score > current_score:
                    scores[end_index] = candidate_score
                    previous[end_index] = start_index

        if scores[count] is None:
            raise ValueError(
                "Narration cannot be grouped into continuous scenes within the "
                f"configured {self.minimum_visual_hold_seconds:.3f}–"
                f"{self.maximum_visual_hold_seconds:.3f}s range using complete "
                "word boundaries. Review the audio alignment or duration settings."
            )

        groups: list[list[_AlignedScene]] = []
        end_index = count
        while end_index:
            start_index = previous[end_index]
            if start_index is None or start_index >= end_index:
                raise RuntimeError("Scene-boundary optimization produced an invalid path.")
            groups.append(aligned[start_index:end_index])
            end_index = start_index
        groups.reverse()
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
        visual_weight = self._visual_weight(group)
        narration_density = len(narration.split()) / max(duration_seconds, 0.001)
        merged = StoryboardScene(
            scene_id=f"scene_{number:03d}", section_id=first.section_id,
            start_seconds=start_seconds, duration_seconds=duration_seconds,
            narration=narration, visual_style=first.visual_style,
            visual_description=visual_description,
            character_action=action, background=background,
            props=props,
            scene_purpose=first.scene_purpose,
            visual_weight=visual_weight,
            narration_density=narration_density,
            hold_reason=self._hold_reason(
                group,
                duration_seconds,
                narration_density,
                visual_weight,
            ),
            text_overlay="",
            timing_boundary=group[0].boundary_before,
            camera_motion="static", transition="cut",
            research_sources=sources, image_prompt="audio-timed placeholder",
        )
        merged.image_prompt = self.prompt_builder.build(merged)
        return merged

    @classmethod
    def _target_hold_seconds(
        cls,
        group: list[_AlignedScene],
        duration: float,
        minimum: float,
        maximum: float,
    ) -> float:
        narration_density = sum(
            len(item.scene.narration.split()) for item in group
        ) / max(duration, 0.001)
        density_factor = min(1.0, max(0.0, (narration_density - 1.2) / 2.4))
        visual_factor = (cls._visual_weight(group) - 1) / 4
        purpose = group[0].scene.scene_purpose
        purpose_adjustment = (
            0.08
            if purpose in {"ESTABLISH", "REVEAL"}
            else -0.08
            if purpose in {"SHOW_PROCESS", "TRANSITION"}
            else 0.0
        )
        preferred_fraction = min(
            1.0,
            max(
                0.0,
                1.0 - (0.65 * density_factor + 0.35 * visual_factor)
                + purpose_adjustment,
            ),
        )
        return minimum + (maximum - minimum) * preferred_fraction

    @classmethod
    def _visual_weight(cls, group: list[_AlignedScene]) -> int:
        descriptions = {
            cls._base_visual_description(item.scene).casefold()
            for item in group
            if cls._base_visual_description(item.scene)
        }
        actions = {
            item.scene.character_action.strip().casefold()
            for item in group
            if item.scene.character_action.strip()
        }
        props = {
            prop.strip().casefold()
            for item in group
            for prop in item.scene.props
            if prop.strip()
        }
        distinct_visuals = len(descriptions) + len(actions) + min(2, len(props))
        return min(5, max(1, distinct_visuals))

    @classmethod
    def _hold_reason(
        cls,
        group: list[_AlignedScene],
        duration: float,
        narration_density: float,
        visual_weight: int,
    ) -> str:
        purpose = group[0].scene.scene_purpose
        natural_internal_boundary = any(
            item.boundary_before in {"sentence", "clause", "pause"}
            for item in group[1:]
        )
        if duration >= 8 and not natural_internal_boundary:
            return "NO_NATURAL_BOUNDARY_FOUND"
        if duration <= 2:
            if narration_density >= 2.5:
                return "HIGH_INFORMATION_DENSITY"
            if visual_weight >= 4:
                return "DISCRETE_VISUAL_BEAT"
            return "RAPID_VISUAL_BEAT"
        if duration >= 5:
            if purpose == "ESTABLISH":
                return "SUSTAINED_SCENE_SETTING"
            if purpose == "REVEAL":
                return "REVEAL"
            if visual_weight <= 2:
                return "SINGLE_VISUAL_IDEA"
            return "DELIBERATE_EXPLANATION"
        return "NORMAL_EXPLANATION"

    @staticmethod
    def _ends_sentence(narration: str) -> bool:
        return bool(re.search(r"""[.!?]["')\]]*$""", narration.strip()))

    @classmethod
    def _boundary_before(
        cls,
        previous_scene: StoryboardScene | None,
        current_scene: StoryboardScene,
        start_seconds: float,
        previous_end_seconds: float,
    ) -> TimingBoundary:
        if previous_scene is None:
            return "audio_start"
        if cls._ends_sentence(previous_scene.narration):
            return "sentence"
        if start_seconds - previous_end_seconds >= cls.STRONG_NARRATION_PAUSE_SECONDS:
            return "pause"
        if re.search(r"[,;:—]$", previous_scene.narration.strip()) or re.match(
            r"^(?:and|but|because|while|although|whereas|which|so|when|before|after|then)\b",
            current_scene.narration.strip(),
            re.IGNORECASE,
        ):
            return "clause"
        return "word_fallback"

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
    def _validate_timeline(
        storyboard: Storyboard,
        audio_duration: float,
        minimum_scene_duration: float | None = None,
        maximum_scene_duration: float | None = None,
    ) -> None:
        config = ProductionConfig()
        minimum_scene_duration = (
            config.scene_minimum_duration_seconds
            if minimum_scene_duration is None
            else minimum_scene_duration
        )
        maximum_scene_duration = (
            config.scene_maximum_duration_seconds
            if maximum_scene_duration is None
            else maximum_scene_duration
        )
        assert minimum_scene_duration is not None
        assert maximum_scene_duration is not None
        previous_end = 0.0
        for index, scene in enumerate(storyboard.scenes):
            if scene.start_seconds < 0 or scene.duration_seconds <= 0:
                raise ValueError(f"{scene.scene_id} has invalid timing.")
            if not minimum_scene_duration <= scene.duration_seconds <= maximum_scene_duration:
                raise ValueError(
                    f"{scene.scene_id} lasts {scene.duration_seconds:.3f}s, "
                    f"outside the configured {minimum_scene_duration:.3f}–"
                    f"{maximum_scene_duration:.3f}s scene duration range."
                )
            if index and abs(scene.start_seconds - previous_end) > 0.01:
                raise ValueError(f"{scene.scene_id} is not continuous with the previous scene.")
            previous_end = scene.start_seconds + scene.duration_seconds
        if abs(previous_end - audio_duration) > 0.01:
            raise ValueError("Audio-timed storyboard does not cover the full narration.")
