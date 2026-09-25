import json
import math
from pathlib import Path
from typing import Any

from modules.storyboard.models import Storyboard

from modules.video.engine import VideoAssemblyEngine
from modules.video.models import (
    VideoAssemblyPlan,
    VideoAssemblyRequest,
    VideoClip,
)

from modules.video.sync_models import (
    NarrationAlignment,
    VideoSynchronizationRequest,
    VideoSynchronizationResult,
)


class VideoSynchronizationEngine:
    """
    Synchronizes storyboard scene timing against
    actual character-level narration timestamps.

    The narration timing becomes the source of truth.

    No rendering is performed in this milestone.
    """

    TIMING_TOLERANCE_SECONDS = 0.01

    def create_request(
        self,
        storyboard_file: str | Path,
        assembly_plan_file: str | Path,
        narration_result_file: str | Path,
    ) -> VideoSynchronizationRequest:
        """
        Create a typed synchronization request.
        """

        return VideoSynchronizationRequest(
            storyboard_file=str(
                storyboard_file
            ),
            assembly_plan_file=str(
                assembly_plan_file
            ),
            narration_result_file=str(
                narration_result_file
            ),
        )

    def build_from_request(
        self,
        request: VideoSynchronizationRequest,
    ) -> VideoAssemblyPlan:
        """
        Load all required inputs and create
        a synchronized assembly plan.
        """

        storyboard = self._load_storyboard(
            request.storyboard_file
        )

        assembly_plan = (
            VideoAssemblyEngine.load_plan(
                request.assembly_plan_file
            )
        )

        alignment = self.load_narration_alignment(
            request.narration_result_file
        )

        return self.synchronize_plan(
            storyboard=storyboard,
            assembly_plan=assembly_plan,
            alignment=alignment,
        )

    def run(
        self,
        request: VideoSynchronizationRequest,
        output_plan_file: str | Path,
    ) -> VideoSynchronizationResult:
        """
        Synchronize and save the resulting plan.
        """

        try:
            plan = self.build_from_request(
                request
            )

            saved_path = (
                VideoAssemblyEngine.save_plan(
                    plan,
                    output_plan_file,
                )
            )

            return VideoSynchronizationResult(
                status="completed",
                plan_file=str(saved_path),
                scene_count=len(plan.clips),
                total_duration_seconds=(
                    plan.total_duration_seconds
                ),
                error_message=None,
            )

        except Exception as exc:
            return VideoSynchronizationResult(
                status="failed",
                plan_file=None,
                scene_count=0,
                total_duration_seconds=0,
                error_message=str(exc),
            )

    def synchronize_plan(
        self,
        storyboard: Storyboard,
        assembly_plan: VideoAssemblyPlan,
        alignment: NarrationAlignment,
    ) -> VideoAssemblyPlan:
        """
        Synchronize an existing assembly plan
        against actual narration timing.
        """

        if storyboard.topic != assembly_plan.topic:
            raise ValueError(
                "Storyboard topic does not match "
                "the assembly plan topic."
            )

        if not storyboard.scenes:
            raise ValueError(
                "Cannot synchronize an empty storyboard."
            )

        if not assembly_plan.clips:
            raise ValueError(
                "Cannot synchronize an assembly plan "
                "with no clips."
            )

        if len(storyboard.scenes) != len(
            assembly_plan.clips
        ):
            raise ValueError(
                "Storyboard scene count does not match "
                "assembly plan clip count."
            )

        self._validate_alignment(
            alignment
        )

        scene_matches = (
            self._match_scene_narration(
                storyboard,
                alignment,
            )
        )

        synchronized_clips: list[VideoClip] = []

        for index, (
            scene,
            original_clip,
            match,
        ) in enumerate(
            zip(
                storyboard.scenes,
                assembly_plan.clips,
                scene_matches,
            )
        ):
            start_seconds = (
                0.0
                if index == 0
                else match["start_seconds"]
            )

            if index < len(scene_matches) - 1:
                end_seconds = scene_matches[
                    index + 1
                ]["start_seconds"]
            else:
                end_seconds = (
                    alignment.audio_duration_seconds
                )

            duration_seconds = (
                end_seconds
                - start_seconds
            )

            if duration_seconds <= 0:
                raise ValueError(
                    f"{scene.scene_id} has invalid "
                    "synchronized duration."
                )

            if (
                index < len(scene_matches) - 1
                and match["end_seconds"]
                > end_seconds
                + self.TIMING_TOLERANCE_SECONDS
            ):
                raise ValueError(
                    f"{scene.scene_id} narration overlaps "
                    "the next scene narration."
                )

            synchronized_clips.append(
                VideoClip(
                    scene_id=scene.scene_id,
                    image_path=original_clip.image_path,
                    start_seconds=start_seconds,
                    duration_seconds=duration_seconds,
                    status=original_clip.status,
                )
            )

        synchronized_plan = VideoAssemblyPlan(
            topic=assembly_plan.topic,
            width=assembly_plan.width,
            height=assembly_plan.height,
            fps=assembly_plan.fps,
            clips=synchronized_clips,
            total_duration_seconds=round(
                alignment.audio_duration_seconds,
                3,
            ),
            audio_path=assembly_plan.audio_path,
        )

        self._validate_synchronized_plan(
            synchronized_plan,
            alignment,
        )

        return synchronized_plan

    # -----------------------------------------------------------------
    # Narration alignment loading
    # -----------------------------------------------------------------

    @staticmethod
    def load_narration_alignment(
        narration_result_file: str | Path,
    ) -> NarrationAlignment:
        """
        Load ElevenLabs character alignment data
        from narration_result.json.
        """

        path = Path(
            narration_result_file
        )

        if not path.exists():
            raise FileNotFoundError(
                "Narration result file not found: "
                f"{path}"
            )

        if not path.is_file():
            raise ValueError(
                "Narration result path is not a file: "
                f"{path}"
            )

        data: Any = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, dict):
            raise ValueError(
                "Narration result JSON must contain "
                "an object."
            )

        minimum_duration = data.get("minimum_duration_seconds")
        actual_duration = data.get("actual_duration_seconds")
        if minimum_duration is not None and actual_duration is not None:
            if float(actual_duration) < float(minimum_duration):
                raise ValueError(
                    "Narration audio is shorter than its required minimum; "
                    "it cannot be synchronized."
                )

        alignment_data = data.get(
            "alignment"
        )

        if not isinstance(
            alignment_data,
            dict,
        ):
            alignment_data = data.get(
                "normalized_alignment"
            )

        if not isinstance(
            alignment_data,
            dict,
        ):
            raise ValueError(
                "Narration result does not contain "
                "character alignment data."
            )

        characters = alignment_data.get(
            "characters"
        )

        start_times = alignment_data.get(
            "character_start_times_seconds"
        )

        end_times = alignment_data.get(
            "character_end_times_seconds"
        )

        if not isinstance(
            characters,
            list,
        ):
            raise ValueError(
                "Character alignment data is missing "
                "'characters'."
            )

        if not isinstance(
            start_times,
            list,
        ):
            raise ValueError(
                "Character alignment data is missing "
                "'character_start_times_seconds'."
            )

        if not isinstance(
            end_times,
            list,
        ):
            raise ValueError(
                "Character alignment data is missing "
                "'character_end_times_seconds'."
            )

        duration_value = data.get("actual_duration_seconds")

        if duration_value is None:
            duration_value = data.get("duration_seconds")

        if duration_value is None:
            duration_value = data.get(
                "duration"
            )

        if duration_value is None:
            if not end_times:
                raise ValueError(
                    "Cannot determine audio duration "
                    "from narration alignment."
                )

            duration_value = max(
                float(value)
                for value in end_times
            )

        try:
            audio_duration = float(
                duration_value
            )
        except (
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(
                "Invalid narration audio duration."
            ) from exc

        alignment = NarrationAlignment(
            characters=[
                str(character)
                for character in characters
            ],
            character_start_times_seconds=[
                float(value)
                for value in start_times
            ],
            character_end_times_seconds=[
                float(value)
                for value in end_times
            ],
            audio_duration_seconds=audio_duration,
        )

        VideoSynchronizationEngine._validate_alignment(
            alignment
        )

        return alignment

    # -----------------------------------------------------------------
    # Scene matching
    # -----------------------------------------------------------------

    @staticmethod
    def _compact_text(
        text: str,
    ) -> str:
        """
        Convert text to lowercase alphanumeric
        characters for robust narration matching.
        """

        return "".join(
            character.lower()
            for character in text
            if character.isalnum()
        )

    @staticmethod
    def _build_compact_mapping(
        characters: list[str],
    ) -> tuple[str, list[int]]:
        """
        Build compact text plus a mapping from each
        compact character back to its original index.
        """

        compact_chars: list[str] = []
        original_indices: list[int] = []

        for index, character in enumerate(
            characters
        ):
            compact = (
                character.lower()
                if character.isalnum()
                else ""
            )

            if compact:
                compact_chars.append(
                    compact
                )
                original_indices.append(
                    index
                )

        return (
            "".join(compact_chars),
            original_indices,
        )

    def _match_scene_narration(
        self,
        storyboard: Storyboard,
        alignment: NarrationAlignment,
    ) -> list[dict[str, float]]:
        """
        Match every storyboard narration against
        the character-level ElevenLabs transcript.
        """

        (
            compact_script,
            original_indices,
        ) = self._build_compact_mapping(
            alignment.characters
        )

        matches: list[dict[str, float]] = []

        search_cursor = 0

        for scene in storyboard.scenes:
            scene_text = self._compact_text(
                scene.narration
            )

            if not scene_text:
                raise ValueError(
                    f"{scene.scene_id} has empty narration."
                )

            match_position = compact_script.find(
                scene_text,
                search_cursor,
            )

            if match_position == -1:
                raise ValueError(
                    "Could not match storyboard "
                    f"narration for {scene.scene_id} "
                    "inside the ElevenLabs alignment."
                )

            start_compact_index = (
                match_position
            )

            end_compact_index = (
                match_position
                + len(scene_text)
                - 1
            )

            start_character_index = (
                original_indices[
                    start_compact_index
                ]
            )

            end_character_index = (
                original_indices[
                    end_compact_index
                ]
            )

            start_seconds = (
                alignment
                .character_start_times_seconds[
                    start_character_index
                ]
            )

            end_seconds = (
                alignment
                .character_end_times_seconds[
                    end_character_index
                ]
            )

            matches.append(
                {
                    "start_seconds": start_seconds,
                    "end_seconds": end_seconds,
                }
            )

            search_cursor = (
                match_position
                + len(scene_text)
            )

        return matches

    # -----------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------

    @staticmethod
    def _validate_alignment(
        alignment: NarrationAlignment,
    ) -> None:
        """
        Validate character-level alignment arrays.
        """

        character_count = len(
            alignment.characters
        )

        if character_count == 0:
            raise ValueError(
                "Narration alignment contains no characters."
            )

        if len(
            alignment.character_start_times_seconds
        ) != character_count:
            raise ValueError(
                "Character start timestamp count does "
                "not match character count."
            )

        if len(
            alignment.character_end_times_seconds
        ) != character_count:
            raise ValueError(
                "Character end timestamp count does "
                "not match character count."
            )

        previous_start = 0.0

        for index in range(
            character_count
        ):
            start = (
                alignment
                .character_start_times_seconds[
                    index
                ]
            )

            end = (
                alignment
                .character_end_times_seconds[
                    index
                ]
            )

            if not math.isfinite(start):
                raise ValueError(
                    f"Invalid start timestamp at "
                    f"character {index}."
                )

            if not math.isfinite(end):
                raise ValueError(
                    f"Invalid end timestamp at "
                    f"character {index}."
                )

            if start < 0:
                raise ValueError(
                    f"Negative start timestamp at "
                    f"character {index}."
                )

            if end < start:
                raise ValueError(
                    f"Character {index} has an end timestamp "
                    "before its start timestamp."
                )

            if start + 0.000001 < previous_start:
                raise ValueError(
                    "Narration start timestamps are "
                    "not sequential."
                )

            previous_start = start

        final_end = max(
            alignment.character_end_times_seconds
        )

        if final_end > (
            alignment.audio_duration_seconds
            + 0.25
        ):
            raise ValueError(
                "Final alignment timestamp exceeds "
                "the narration audio duration."
            )

    @staticmethod
    def _validate_synchronized_plan(
        plan: VideoAssemblyPlan,
        alignment: NarrationAlignment,
    ) -> None:
        """
        Validate the final synchronized timeline.
        """

        if not plan.clips:
            raise ValueError(
                "Synchronized plan contains no clips."
            )

        previous_end = 0.0

        for index, clip in enumerate(
            plan.clips
        ):
            if clip.start_seconds < 0:
                raise ValueError(
                    f"{clip.scene_id} has a negative start time."
                )

            if clip.duration_seconds <= 0:
                raise ValueError(
                    f"{clip.scene_id} has an invalid duration."
                )

            if index > 0:
                if abs(
                    clip.start_seconds
                    - previous_end
                ) > 0.01:
                    raise ValueError(
                        f"{clip.scene_id} is not continuous "
                        "with the previous clip."
                    )

            previous_end = (
                clip.start_seconds
                + clip.duration_seconds
            )

        if abs(
            plan.total_duration_seconds
            - alignment.audio_duration_seconds
        ) > 0.01:
            raise ValueError(
                "Synchronized video duration does not "
                "match narration duration."
            )

        if abs(
            previous_end
            - alignment.audio_duration_seconds
        ) > 0.01:
            raise ValueError(
                "Synchronized clip timeline does not "
                "end at the narration duration."
            )

    # -----------------------------------------------------------------
    # Storyboard loading
    # -----------------------------------------------------------------

    @staticmethod
    def _load_storyboard(
        storyboard_file: str | Path,
    ) -> Storyboard:
        """
        Load storyboard JSON.
        """

        path = Path(
            storyboard_file
        )

        if not path.exists():
            raise FileNotFoundError(
                "Storyboard file not found: "
                f"{path}"
            )

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return Storyboard.model_validate(
            data
        )
