import json
from pathlib import Path

from modules.script.models import Script
from modules.storyboard.models import (
    CameraMotion,
    Storyboard,
    StoryboardScene,
)


class StoryboardEngine:
    """Creates and manages visual storyboards for Ritzz videos."""

    def __init__(
        self,
        target_scene_duration_seconds: float = 5.0,
    ) -> None:
        if target_scene_duration_seconds <= 0:
            raise ValueError(
                "Target scene duration must be greater than zero."
            )

        self.target_scene_duration_seconds = (
            target_scene_duration_seconds
        )

    # ---------------------------------------------------------
    # Public API
    # ---------------------------------------------------------

    def create_storyboard(
        self,
        script_file: str | Path,
        output_file: str | Path | None = None,
    ) -> Storyboard:
        """Create a storyboard from an existing script."""

        script = self.load_script(script_file)

        storyboard = self._build_storyboard(script)

        self._validate_storyboard(
            storyboard,
            script,
        )

        if output_file is not None:
            self.save_storyboard(
                storyboard,
                output_file,
            )

        return storyboard

    # ---------------------------------------------------------
    # Script loading
    # ---------------------------------------------------------

    @staticmethod
    def load_script(
        script_file: str | Path,
    ) -> Script:
        """Load a Script from JSON."""

        path = Path(script_file)

        if not path.exists():
            raise FileNotFoundError(
                f"Script file not found: {path}"
            )

        data = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )

        return Script.model_validate(data)

    # ---------------------------------------------------------
    # Storyboard construction
    # ---------------------------------------------------------

    def _build_storyboard(
        self,
        script: Script,
    ) -> Storyboard:
        """
        Build a visual storyboard from the script.

        Editorial text is optional. The storyboard engine does
        not force text onto every scene and does not automatically
        convert narration into image text.

        When editorial text is not intentionally assigned,
        text_overlay remains empty.
        """

        scenes: list[StoryboardScene] = []

        current_time = 0.0
        scene_number = 1

        for section in script.sections:
            narration = section.narration.strip()

            if not narration:
                raise ValueError(
                    f"Section {section.section_id} "
                    "has no narration."
                )

            word_count = len(
                narration.split()
            )

            if word_count == 0:
                raise ValueError(
                    f"Section {section.section_id} "
                    "contains no words."
                )

            section_duration = float(
                section.estimated_seconds
            )

            section_scene_count = max(
                1,
                round(
                    section_duration
                    / self.target_scene_duration_seconds
                ),
            )

            word_groups = self._split_words(
                narration.split(),
                section_scene_count,
            )

            actual_scene_count = len(
                word_groups
            )

            base_duration = (
                section_duration
                / actual_scene_count
            )

            for index, words in enumerate(
                word_groups
            ):
                scene_duration = base_duration

                scene_narration = " ".join(words)

                scene_id = (
                    f"scene_{scene_number:03d}"
                )

                visual_description = (
                    self._build_visual_description(
                        section.title,
                        scene_narration,
                    )
                )

                image_prompt = (
                    self._build_image_prompt(
                        section.title,
                        scene_narration,
                    )
                )

                camera_motion = (
                    self._select_camera_motion(
                        scene_number
                    )
                )

                transition = (
                    "fade"
                    if index == 0
                    and scene_number > 1
                    else "cut"
                )

                # Editorial text is intentionally optional.
                #
                # Do NOT automatically copy narration here.
                # Do NOT force text onto every scene.
                #
                # Future storyboard intelligence can selectively
                # populate this with short visual callouts such as:
                # "THE MYSTERY"
                # "WILD SIZE"
                # "10× LARGER"
                # "THE REAL REASON"
                editorial_text = ""

                scene = StoryboardScene(
                    scene_id=scene_id,
                    section_id=section.section_id,
                    start_seconds=round(
                        current_time,
                        2,
                    ),
                    duration_seconds=round(
                        scene_duration,
                        2,
                    ),
                    narration=scene_narration,
                    visual_style="stickman",
                    visual_description=visual_description,
                    character_action=(
                        "Express the main idea "
                        "of the narration."
                    ),
                    background=(
                        "Simple clean illustrated "
                        "background relevant to "
                        "the narration."
                    ),
                    props=[],
                    text_overlay=editorial_text,
                    camera_motion=camera_motion,
                    transition=transition,
                    research_sources=list(
                        section.research_sources
                    ),
                    image_prompt=image_prompt,
                )

                scenes.append(scene)

                current_time += scene_duration
                scene_number += 1

        total_duration = sum(
            scene.duration_seconds
            for scene in scenes
        )

        return Storyboard(
            topic=script.topic,
            target_duration_seconds=(
                script.target_duration_seconds
            ),
            scenes=scenes,
            total_scene_duration_seconds=round(
                total_duration,
                2,
            ),
            target_scene_duration_seconds=(
                self.target_scene_duration_seconds
            ),
        )

    # ---------------------------------------------------------
    # Word splitting
    # ---------------------------------------------------------

    @staticmethod
    def _split_words(
        words: list[str],
        number_of_groups: int,
    ) -> list[list[str]]:
        """Split words into approximately equal groups."""

        if not words:
            return [[]]

        number_of_groups = max(
            1,
            min(
                number_of_groups,
                len(words),
            ),
        )

        result: list[list[str]] = []

        base_size = (
            len(words)
            // number_of_groups
        )

        remainder = (
            len(words)
            % number_of_groups
        )

        start = 0

        for index in range(
            number_of_groups
        ):
            size = base_size

            if index < remainder:
                size += 1

            end = start + size

            result.append(
                words[start:end]
            )

            start = end

        return result

    # ---------------------------------------------------------
    # Visual generation helpers
    # ---------------------------------------------------------

    @staticmethod
    def _build_visual_description(
        title: str,
        narration: str,
    ) -> str:
        """Create a basic visual description."""

        return (
            f"Simple hand-drawn stick-man explainer "
            f"scene illustrating the idea in "
            f"'{title}'. The character should visually "
            f"represent this narration: {narration}"
        )

    @staticmethod
    def _build_image_prompt(
        title: str,
        narration: str,
    ) -> str:
        """Create a basic image-generation prompt."""

        return (
            "Ritzz visual style: simple hand-drawn "
            "2D stick-man explainer illustration, "
            "clean composition, strong black outlines, "
            "minimal background, readable visual "
            "storytelling, consistent character design. "
            f"Scene topic: {title}. "
            f"Visual idea: {narration}. "
            "No photorealism, no 3D rendering, "
            "no unnecessary visual clutter."
        )

    @staticmethod
    def _select_camera_motion(
        scene_number: int,
    ) -> CameraMotion:
        """Select restrained camera movement."""

        motions: list[CameraMotion] = [
            "static",
            "slow_zoom_in",
            "slow_zoom_out",
            "pan_left",
            "pan_right",
        ]

        return motions[
            (scene_number - 1)
            % len(motions)
        ]

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    @staticmethod
    def _validate_storyboard(
        storyboard: Storyboard,
        script: Script,
    ) -> None:
        """Validate storyboard consistency."""

        if storyboard.topic != script.topic:
            raise ValueError(
                "Storyboard topic does not match "
                "the source script."
            )

        if not storyboard.scenes:
            raise ValueError(
                "Storyboard contains no scenes."
            )

        expected_duration = float(
            script.total_estimated_seconds
        )

        actual_duration = sum(
            scene.duration_seconds
            for scene in storyboard.scenes
        )

        if abs(
            actual_duration
            - expected_duration
        ) > 0.1:
            raise ValueError(
                "Storyboard duration mismatch: "
                f"scenes total {actual_duration:.2f}s, "
                f"but script reports "
                f"{expected_duration:.2f}s."
            )

        if abs(
            storyboard.total_scene_duration_seconds
            - actual_duration
        ) > 0.1:
            raise ValueError(
                "Storyboard reported duration does "
                "not match its scene durations."
            )

        script_section_ids = {
            section.section_id
            for section in script.sections
        }

        storyboard_section_ids = {
            scene.section_id
            for scene in storyboard.scenes
        }

        missing_sections = (
            script_section_ids
            - storyboard_section_ids
        )

        if missing_sections:
            raise ValueError(
                "Storyboard is missing script "
                f"sections: {sorted(missing_sections)}"
            )

        for scene in storyboard.scenes:
            if not scene.narration.strip():
                raise ValueError(
                    f"{scene.scene_id} has empty narration."
                )

            if not scene.image_prompt.strip():
                raise ValueError(
                    f"{scene.scene_id} has no image prompt."
                )

            # Editorial text is optional.
            # When present, Pydantic validates the maximum
            # length through StoryboardScene.text_overlay.
            if scene.text_overlay:
                if not scene.text_overlay.strip():
                    raise ValueError(
                        f"{scene.scene_id} has invalid "
                        "editorial text."
                    )

    # ---------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------

    @staticmethod
    def save_storyboard(
        storyboard: Storyboard,
        output_file: str | Path,
    ) -> Path:
        """Save storyboard as JSON."""

        path = Path(output_file)

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                storyboard.model_dump(),
                indent=4,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return path

    @staticmethod
    def load_storyboard(
        storyboard_file: str | Path,
    ) -> Storyboard:
        """Load a storyboard from JSON."""

        path = Path(storyboard_file)

        if not path.exists():
            raise FileNotFoundError(
                f"Storyboard file not found: {path}"
            )

        data = json.loads(
            path.read_text(
                encoding="utf-8",
            )
        )

        return Storyboard.model_validate(data)