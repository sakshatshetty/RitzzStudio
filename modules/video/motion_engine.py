import json
from pathlib import Path

from modules.project.config import EditingStyle
from modules.storyboard.models import Storyboard

from modules.video.engine import VideoAssemblyEngine
from modules.video.models import VideoAssemblyPlan

from modules.video.motion_models import (
    MotionInstruction,
    VideoMotionPlan,
    VideoMotionRequest,
    VideoMotionResult,
)


class VideoMotionEngine:
    """
    Builds automated zoom/pan instructions for
    each video scene.

    This milestone creates the motion plan only.
    Actual FFmpeg rendering is handled later.
    """

    ZOOM_AMOUNT = 0.10
    HISTORY_ZOOM_AMOUNT = 0.05

    PAN_CENTER = 0.50
    PAN_START = 0.40
    PAN_END = 0.60

    def create_request(
        self,
        storyboard_file: str | Path,
        assembly_plan_file: str | Path,
        editing_style: EditingStyle = "hard_cut",
    ) -> VideoMotionRequest:
        """
        Create a typed motion request.
        """

        return VideoMotionRequest(
            storyboard_file=str(
                storyboard_file
            ),
            assembly_plan_file=str(
                assembly_plan_file
            ),
            editing_style=editing_style,
        )

    def build_from_request(
        self,
        request: VideoMotionRequest,
    ) -> VideoMotionPlan:
        """
        Load storyboard and assembly plan,
        then create a motion plan.
        """

        storyboard = self.load_storyboard(
            request.storyboard_file
        )

        assembly_plan = (
            VideoAssemblyEngine.load_plan(
                request.assembly_plan_file
            )
        )

        return self.create_plan(
            storyboard=storyboard,
            assembly_plan=assembly_plan,
            editing_style=request.editing_style,
        )

    def create_plan(
        self,
        storyboard: Storyboard,
        assembly_plan: VideoAssemblyPlan,
        editing_style: EditingStyle = "hard_cut",
    ) -> VideoMotionPlan:
        """
        Create motion instructions using the
        camera_motion field from each storyboard scene.
        """

        if not storyboard.scenes:
            raise ValueError(
                "Cannot create a motion plan "
                "from an empty storyboard."
            )

        if not assembly_plan.clips:
            raise ValueError(
                "Cannot create a motion plan "
                "from an empty assembly plan."
            )

        if storyboard.topic != assembly_plan.topic:
            raise ValueError(
                "Storyboard topic does not match "
                "the assembly plan topic."
            )

        if editing_style not in {"hard_cut", "history"}:
            raise ValueError(f"Unsupported editing style: {editing_style}")

        if len(storyboard.scenes) != len(
            assembly_plan.clips
        ):
            raise ValueError(
                "Storyboard scene count does not match "
                "assembly plan clip count."
            )

        instructions: list[
            MotionInstruction
        ] = []

        history_zoom_index = 0
        for scene, clip in zip(
            storyboard.scenes,
            assembly_plan.clips,
        ):
            if scene.scene_id != clip.scene_id:
                raise ValueError(
                    "Storyboard and assembly plan "
                    "scene ordering does not match."
                )

            motion = scene.camera_motion
            if editing_style == "history":
                sentence_text = scene.sentence.strip() or scene.narration.strip()
                if len(sentence_text.split()) >= 12:
                    motion = (
                        "slow_zoom_in"
                        if history_zoom_index % 2 == 0
                        else "slow_zoom_out"
                    )
                    history_zoom_index += 1
                else:
                    motion = "static"

            instruction = (
                self._create_instruction(
                    scene.scene_id,
                    clip.start_seconds,
                    clip.duration_seconds,
                    motion,
                    zoom_amount=(
                        self.HISTORY_ZOOM_AMOUNT
                        if editing_style == "history"
                        else self.ZOOM_AMOUNT
                    ),
                )
            )

            instructions.append(
                instruction
            )

        plan = VideoMotionPlan(
            topic=assembly_plan.topic,
            width=assembly_plan.width,
            height=assembly_plan.height,
            fps=assembly_plan.fps,
            editing_style=editing_style,
            instructions=instructions,
            total_duration_seconds=(
                assembly_plan.total_duration_seconds
            ),
        )

        self._validate_plan(
            plan,
            assembly_plan,
        )

        return plan

    def run(
        self,
        request: VideoMotionRequest,
        output_plan_file: str | Path,
    ) -> VideoMotionResult:
        """
        Create and save a motion plan.
        """

        try:
            plan = self.build_from_request(
                request
            )

            saved_path = self.save_plan(
                plan,
                output_plan_file,
            )

            return VideoMotionResult(
                status="completed",
                plan_file=str(
                    saved_path
                ),
                scene_count=len(
                    plan.instructions
                ),
                total_duration_seconds=(
                    plan.total_duration_seconds
                ),
                error_message=None,
            )

        except Exception as exc:
            return VideoMotionResult(
                status="failed",
                plan_file=None,
                scene_count=0,
                total_duration_seconds=0,
                error_message=str(exc),
            )

    # -----------------------------------------------------------------
    # Motion mapping
    # -----------------------------------------------------------------

    def _create_instruction(
        self,
        scene_id: str,
        start_seconds: float,
        duration_seconds: float,
        motion: str,
        *,
        zoom_amount: float,
    ) -> MotionInstruction:
        """
        Convert storyboard camera motion into
        normalized motion parameters.
        """

        if motion == "static":
            return MotionInstruction(
                scene_id=scene_id,
                start_seconds=start_seconds,
                duration_seconds=duration_seconds,
                motion="static",
                zoom_start=1.0,
                zoom_end=1.0,
                position_x_start=self.PAN_CENTER,
                position_x_end=self.PAN_CENTER,
                position_y_start=self.PAN_CENTER,
                position_y_end=self.PAN_CENTER,
            )

        if motion == "slow_zoom_in":
            return MotionInstruction(
                scene_id=scene_id,
                start_seconds=start_seconds,
                duration_seconds=duration_seconds,
                motion="slow_zoom_in",
                zoom_start=1.0,
                zoom_end=1.0 + zoom_amount,
                position_x_start=self.PAN_CENTER,
                position_x_end=self.PAN_CENTER,
                position_y_start=self.PAN_CENTER,
                position_y_end=self.PAN_CENTER,
            )

        if motion == "slow_zoom_out":
            return MotionInstruction(
                scene_id=scene_id,
                start_seconds=start_seconds,
                duration_seconds=duration_seconds,
                motion="slow_zoom_out",
                zoom_start=1.0 + zoom_amount,
                zoom_end=1.0,
                position_x_start=self.PAN_CENTER,
                position_x_end=self.PAN_CENTER,
                position_y_start=self.PAN_CENTER,
                position_y_end=self.PAN_CENTER,
            )

        if motion == "pan_left":
            return MotionInstruction(
                scene_id=scene_id,
                start_seconds=start_seconds,
                duration_seconds=duration_seconds,
                motion="pan_left",
                zoom_start=1.0 + self.ZOOM_AMOUNT,
                zoom_end=1.0 + self.ZOOM_AMOUNT,
                position_x_start=self.PAN_END,
                position_x_end=self.PAN_START,
                position_y_start=self.PAN_CENTER,
                position_y_end=self.PAN_CENTER,
            )

        if motion == "pan_right":
            return MotionInstruction(
                scene_id=scene_id,
                start_seconds=start_seconds,
                duration_seconds=duration_seconds,
                motion="pan_right",
                zoom_start=1.0 + self.ZOOM_AMOUNT,
                zoom_end=1.0 + self.ZOOM_AMOUNT,
                position_x_start=self.PAN_START,
                position_x_end=self.PAN_END,
                position_y_start=self.PAN_CENTER,
                position_y_end=self.PAN_CENTER,
            )

        if motion == "pan_up":
            return MotionInstruction(
                scene_id=scene_id,
                start_seconds=start_seconds,
                duration_seconds=duration_seconds,
                motion="pan_up",
                zoom_start=1.0 + self.ZOOM_AMOUNT,
                zoom_end=1.0 + self.ZOOM_AMOUNT,
                position_x_start=self.PAN_CENTER,
                position_x_end=self.PAN_CENTER,
                position_y_start=self.PAN_END,
                position_y_end=self.PAN_START,
            )

        if motion == "pan_down":
            return MotionInstruction(
                scene_id=scene_id,
                start_seconds=start_seconds,
                duration_seconds=duration_seconds,
                motion="pan_down",
                zoom_start=1.0 + self.ZOOM_AMOUNT,
                zoom_end=1.0 + self.ZOOM_AMOUNT,
                position_x_start=self.PAN_CENTER,
                position_x_end=self.PAN_CENTER,
                position_y_start=self.PAN_START,
                position_y_end=self.PAN_END,
            )

        raise ValueError(
            f"Unsupported camera motion: {motion}"
        )

    # -----------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------

    @staticmethod
    def _validate_plan(
        plan: VideoMotionPlan,
        assembly_plan: VideoAssemblyPlan,
    ) -> None:
        """
        Validate the motion plan against the
        assembly timeline.
        """

        if len(plan.instructions) != len(
            assembly_plan.clips
        ):
            raise ValueError(
                "Motion instruction count does not match "
                "assembly clip count."
            )

        previous_end = 0.0

        for index, (
            instruction,
            clip,
        ) in enumerate(
            zip(
                plan.instructions,
                assembly_plan.clips,
            )
        ):
            if instruction.scene_id != clip.scene_id:
                raise ValueError(
                    "Motion instruction scene ordering "
                    f"mismatch at index {index}."
                )

            if abs(
                instruction.start_seconds
                - clip.start_seconds
            ) > 0.01:
                raise ValueError(
                    f"{instruction.scene_id} motion start "
                    "does not match assembly timeline."
                )

            if abs(
                instruction.duration_seconds
                - clip.duration_seconds
            ) > 0.01:
                raise ValueError(
                    f"{instruction.scene_id} motion duration "
                    "does not match assembly timeline."
                )

            if index > 0:
                if abs(
                    instruction.start_seconds
                    - previous_end
                ) > 0.01:
                    raise ValueError(
                        f"{instruction.scene_id} motion timeline "
                        "is not continuous."
                    )

            previous_end = (
                instruction.start_seconds
                + instruction.duration_seconds
            )

            for value in (
                instruction.position_x_start,
                instruction.position_x_end,
                instruction.position_y_start,
                instruction.position_y_end,
            ):
                if not 0.0 <= value <= 1.0:
                    raise ValueError(
                        f"{instruction.scene_id} contains "
                        "an invalid normalized position."
                    )

            if instruction.zoom_start <= 0:
                raise ValueError(
                    f"{instruction.scene_id} has invalid "
                    "starting zoom."
                )

            if instruction.zoom_end <= 0:
                raise ValueError(
                    f"{instruction.scene_id} has invalid "
                    "ending zoom."
                )

        if abs(
            plan.total_duration_seconds
            - assembly_plan.total_duration_seconds
        ) > 0.01:
            raise ValueError(
                "Motion plan duration does not match "
                "assembly duration."
            )

        if abs(
            previous_end
            - assembly_plan.total_duration_seconds
        ) > 0.01:
            raise ValueError(
                "Motion timeline does not reach "
                "the end of the assembly."
            )

    # -----------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------

    @staticmethod
    def save_plan(
        plan: VideoMotionPlan,
        output_file: str | Path,
    ) -> Path:
        """
        Save motion plan as JSON.
        """

        path = Path(
            output_file
        )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                plan.model_dump(),
                indent=4,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        return path

    @staticmethod
    def load_plan(
        plan_file: str | Path,
    ) -> VideoMotionPlan:
        """
        Load motion plan from JSON.
        """

        path = Path(
            plan_file
        )

        if not path.exists():
            raise FileNotFoundError(
                f"Motion plan not found: {path}"
            )

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return VideoMotionPlan.model_validate(
            data
        )

    # -----------------------------------------------------------------
    # Storyboard loading
    # -----------------------------------------------------------------

    @staticmethod
    def load_storyboard(
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
                f"Storyboard file not found: {path}"
            )

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return Storyboard.model_validate(
            data
        )