"""Timestamp one still-image scene to each complete narrated sentence."""

from pathlib import Path

from modules.image.prompt_builder import ImagePromptBuilder
from modules.project.config import ProductionConfig
from modules.script.sentences import split_sentences
from modules.storyboard.models import Storyboard, StoryboardScene
from modules.video.sync_engine import VideoSynchronizationEngine
from modules.video.sync_models import NarrationAlignment


class AudioTimedStoryboardEngine:
    """Use character-level narration timestamps for sentence-aligned stills."""

    TIMING_TOLERANCE_SECONDS = 0.01

    def __init__(
        self,
        prompt_builder: ImagePromptBuilder | None = None,
        production_config: ProductionConfig | None = None,
    ) -> None:
        self.prompt_builder = prompt_builder or ImagePromptBuilder()
        del production_config

    def build(
        self,
        storyboard: Storyboard,
        alignment: NarrationAlignment,
    ) -> Storyboard:
        if not storyboard.scenes:
            raise ValueError("Cannot time an empty storyboard.")

        VideoSynchronizationEngine._validate_alignment(alignment)
        for scene in storyboard.scenes:
            sentences = split_sentences(scene.narration.strip())
            if len(sentences) != 1 or sentences[0] != scene.narration.strip():
                raise ValueError(
                    f"{scene.scene_id} must contain exactly one complete sentence."
                )

        matches = VideoSynchronizationEngine()._match_scene_narration(
            storyboard,
            alignment,
        )
        scenes: list[StoryboardScene] = []
        for index, (source_scene, match) in enumerate(
            zip(storyboard.scenes, matches, strict=True)
        ):
            start = 0.0 if index == 0 else match["start_seconds"]
            end = (
                matches[index + 1]["start_seconds"]
                if index + 1 < len(matches)
                else alignment.audio_duration_seconds
            )
            if end <= start:
                raise ValueError(
                    f"{source_scene.scene_id} has a non-positive sentence interval."
                )
            if match["end_seconds"] > end + self.TIMING_TOLERANCE_SECONDS:
                raise ValueError(
                    f"{source_scene.scene_id} narration overlaps the next sentence "
                    "in the character-level audio alignment."
                )

            sentence = source_scene.sentence or source_scene.narration.strip()
            scene = source_scene.model_copy(
                update={
                    "sentence_id": index + 1,
                    "sentence": sentence,
                    "sentence_start_seconds": start,
                    "sentence_end_seconds": end,
                    "start_seconds": start,
                    "duration_seconds": end - start,
                    "previous_sentence": (
                        storyboard.scenes[index - 1].narration
                        if index
                        else ""
                    ),
                    "next_sentence": (
                        storyboard.scenes[index + 1].narration
                        if index + 1 < len(storyboard.scenes)
                        else ""
                    ),
                    "timing_boundary": "audio_start" if index == 0 else "sentence",
                    "camera_motion": "static",
                    "transition": "cut",
                }
            )
            scene.image_prompt = self.prompt_builder.build(
                scene,
                project_topic=storyboard.topic,
            )
            scenes.append(scene)

        result = Storyboard(
            topic=storyboard.topic,
            target_duration_seconds=round(alignment.audio_duration_seconds),
            scenes=scenes,
            total_scene_duration_seconds=alignment.audio_duration_seconds,
            target_scene_duration_seconds=None,
        )
        self._validate_timeline(result, alignment.audio_duration_seconds)
        return result

    @staticmethod
    def validate_alignment(
        storyboard: Storyboard,
        alignment: NarrationAlignment,
    ) -> None:
        """Verify saved sentence scenes against the real character timestamps."""
        VideoSynchronizationEngine._validate_alignment(alignment)
        for scene in storyboard.scenes:
            if split_sentences(scene.narration.strip()) != [
                scene.narration.strip()
            ]:
                raise ValueError(
                    f"{scene.scene_id} must contain exactly one complete sentence."
                )
        matches = VideoSynchronizationEngine()._match_scene_narration(
            storyboard,
            alignment,
        )
        if len(matches) != len(storyboard.scenes):
            raise ValueError(
                "Sentence count does not match the narration alignment."
            )
        for index, (scene, match) in enumerate(
            zip(storyboard.scenes, matches, strict=True)
        ):
            expected_start = 0.0 if index == 0 else match["start_seconds"]
            expected_end = (
                matches[index + 1]["start_seconds"]
                if index + 1 < len(matches)
                else alignment.audio_duration_seconds
            )
            if match["end_seconds"] > expected_end + 0.01:
                raise ValueError(
                    f"{scene.scene_id} overlaps the following sentence in narration."
                )
            if (
                scene.sentence_id != index + 1
                or scene.sentence != scene.narration.strip()
                or abs(scene.start_seconds - expected_start) > 0.01
                or abs(
                    scene.start_seconds + scene.duration_seconds - expected_end
                )
                > 0.01
            ):
                raise ValueError(
                    f"{scene.scene_id} timing does not match the sentence's "
                    "actual narration interval."
                )
        AudioTimedStoryboardEngine._validate_timeline(
            storyboard,
            alignment.audio_duration_seconds,
        )

    @staticmethod
    def save_storyboard(
        storyboard: Storyboard,
        output_file: str | Path,
        production_config: ProductionConfig | None = None,
    ) -> Path:
        del production_config
        path = Path(output_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        from modules.qa.engine import record_stage_qa

        project_directory = (
            path.parent.parent
            if path.parent.name == "storyboard"
            else path.parent
        )
        initial_qa = AudioTimedStoryboardEngine._evaluate_storyboard(storyboard)
        if initial_qa.status != "PASS":
            record_stage_qa(project_directory, initial_qa)

        repaired = AudioTimedStoryboardEngine._repair_storyboard(storyboard)
        final_qa = AudioTimedStoryboardEngine._evaluate_storyboard(repaired)
        path.write_text(repaired.model_dump_json(indent=2), encoding="utf-8")
        record_stage_qa(project_directory, final_qa)
        if final_qa.status == "FAIL":
            raise ValueError(
                "Sentence-aligned storyboard QA failed; inspect "
                "qa/qa_report.json before image generation."
            )
        return path

    @staticmethod
    def _evaluate_storyboard(
        storyboard: Storyboard,
        production_config: ProductionConfig | None = None,
    ):
        from modules.qa.models import QAStageResult

        del production_config
        sentence_mapping_valid = bool(storyboard.scenes) and all(
            scene.sentence_id == index
            and scene.sentence == scene.narration.strip()
            and split_sentences(scene.sentence) == [scene.sentence]
            and scene.sentence_start_seconds is not None
            and scene.sentence_end_seconds is not None
            and abs(scene.start_seconds - scene.sentence_start_seconds) <= 0.01
            and abs(
                scene.start_seconds + scene.duration_seconds
                - scene.sentence_end_seconds
            )
            <= 0.01
            for index, scene in enumerate(storyboard.scenes, start=1)
        )
        prompts_valid = bool(storyboard.scenes) and all(
            scene.image_prompt.strip() for scene in storyboard.scenes
        )
        static_camera = all(
            scene.camera_motion == "static" for scene in storyboard.scenes
        )
        hard_cuts = all(scene.transition == "cut" for scene in storyboard.scenes)
        try:
            AudioTimedStoryboardEngine._validate_timeline(
                storyboard,
                storyboard.total_scene_duration_seconds,
            )
            timeline_valid = True
        except ValueError:
            timeline_valid = False

        findings = []
        if not sentence_mapping_valid:
            findings.append(
                "Every storyboard scene must map one-to-one to a single "
                "sentence and its aligned image interval."
            )
        if not timeline_valid:
            findings.append(
                "Sentence image intervals have gaps, overlaps, or incomplete "
                "audio coverage."
            )
        if not prompts_valid:
            findings.append("One or more sentences have no production image prompt.")
        if not static_camera:
            findings.append("One or more production scenes are not static-camera.")
        if not hard_cuts:
            findings.append("One or more production scenes do not use hard cuts.")

        hard_checks_pass = (
            sentence_mapping_valid
            and timeline_valid
            and prompts_valid
            and static_camera
            and hard_cuts
        )
        return QAStageResult(
            stage="storyboard",
            status="PASS" if hard_checks_pass else "FAIL",
            checks={
                "sentence_scene_mapping": (
                    "PASS" if sentence_mapping_valid else "FAIL"
                ),
                "timeline_coverage": "PASS" if timeline_valid else "FAIL",
                "scene_prompts": "PASS" if prompts_valid else "FAIL",
                "static_camera": "PASS" if static_camera else "FAIL",
                "hard_cuts": "PASS" if hard_cuts else "FAIL",
            },
            findings=findings,
            recommendations=[],
        )

    @staticmethod
    def _repair_storyboard(storyboard: Storyboard) -> Storyboard:
        prompt_builder = ImagePromptBuilder()
        scenes = [
            scene.model_copy(
                update={
                    "camera_motion": "static",
                    "transition": "cut",
                    "image_prompt": (
                        prompt_builder.build(
                            scene,
                            project_topic=storyboard.topic,
                        )
                        if not scene.image_prompt.strip()
                        else scene.image_prompt
                    ),
                }
            )
            for scene in storyboard.scenes
        ]
        return storyboard.model_copy(update={"scenes": scenes})

    @staticmethod
    def _validate_timeline(
        storyboard: Storyboard,
        audio_duration: float,
    ) -> None:
        previous_end = 0.0
        for index, scene in enumerate(storyboard.scenes):
            if scene.start_seconds < 0 or scene.duration_seconds <= 0:
                raise ValueError(f"{scene.scene_id} has invalid timing.")
            if index and abs(scene.start_seconds - previous_end) > 0.01:
                raise ValueError(
                    f"{scene.scene_id} is not continuous with the previous scene."
                )
            previous_end = scene.start_seconds + scene.duration_seconds
        if abs(previous_end - audio_duration) > 0.01:
            raise ValueError(
                "Audio-timed storyboard does not cover the full narration."
            )
