import json
from pathlib import Path

from modules.storyboard.models import Storyboard

from modules.video.models import (
    VideoAssemblyPlan,
    VideoAssemblyRequest,
    VideoClip,
)


class VideoAssemblyEngine:
    """
    Builds the static video timeline from a storyboard
    and its corresponding image assets.

    This engine does not render the final video yet.
    """

    DEFAULT_WIDTH = 1536
    DEFAULT_HEIGHT = 864
    DEFAULT_FPS = 30

    def __init__(
        self,
        width: int = DEFAULT_WIDTH,
        height: int = DEFAULT_HEIGHT,
        fps: int = DEFAULT_FPS,
    ) -> None:
        if width <= 0:
            raise ValueError(
                "Video width must be greater than zero."
            )

        if height <= 0:
            raise ValueError(
                "Video height must be greater than zero."
            )

        if fps <= 0:
            raise ValueError(
                "Video FPS must be greater than zero."
            )

        self.width = width
        self.height = height
        self.fps = fps

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def create_plan(
        self,
        storyboard: Storyboard,
        image_directory: str | Path,
        audio_file: str | Path | None = None,
    ) -> VideoAssemblyPlan:
        """
        Build a video assembly plan from a storyboard.
        """

        image_dir = Path(
            image_directory
        )

        if not image_dir.exists():
            raise FileNotFoundError(
                f"Image directory not found: {image_dir}"
            )

        if not image_dir.is_dir():
            raise ValueError(
                f"Image path is not a directory: {image_dir}"
            )

        audio_path = self._validate_audio_file(
            audio_file
        )

        clips: list[VideoClip] = []

        for scene in storyboard.scenes:
            image_path = (
                image_dir
                / f"{scene.scene_id}.png"
            )

            status = self._validate_image_file(
                image_path
            )

            if status != "ready":
                raise ValueError(
                    "Missing or invalid image for "
                    f"{scene.scene_id}: {image_path}"
                )

            clips.append(
                VideoClip(
                    scene_id=scene.scene_id,
                    image_path=str(
                        image_path
                    ),
                    start_seconds=scene.start_seconds,
                    duration_seconds=scene.duration_seconds,
                    status="ready",
                )
            )

        if not clips:
            raise ValueError(
                "Cannot create a video assembly plan "
                "from an empty storyboard."
            )

        total_duration = sum(
            clip.duration_seconds
            for clip in clips
        )

        plan = VideoAssemblyPlan(
            topic=storyboard.topic,
            width=self.width,
            height=self.height,
            fps=self.fps,
            clips=clips,
            total_duration_seconds=round(
                total_duration,
                2,
            ),
            audio_path=audio_path,
        )

        self._validate_plan(
            plan,
            storyboard,
        )

        return plan

    def create_request(
        self,
        storyboard_file: str | Path,
        image_directory: str | Path,
        audio_file: str | Path | None = None,
    ) -> VideoAssemblyRequest:
        """
        Create a typed assembly request.
        """

        return VideoAssemblyRequest(
            storyboard_file=str(
                storyboard_file
            ),
            image_directory=str(
                image_directory
            ),
            audio_file=(
                str(audio_file)
                if audio_file is not None
                else None
            ),
            width=self.width,
            height=self.height,
            fps=self.fps,
        )

    def build_from_request(
        self,
        request: VideoAssemblyRequest,
    ) -> VideoAssemblyPlan:
        """
        Load the storyboard and build the assembly plan.
        """

        storyboard = self.load_storyboard(
            request.storyboard_file
        )

        engine = VideoAssemblyEngine(
            width=request.width,
            height=request.height,
            fps=request.fps,
        )

        return engine.create_plan(
            storyboard=storyboard,
            image_directory=request.image_directory,
            audio_file=request.audio_file,
        )

    # -----------------------------------------------------------------
    # Storyboard loading
    # -----------------------------------------------------------------

    @staticmethod
    def load_storyboard(
        storyboard_file: str | Path,
    ) -> Storyboard:
        """
        Load a storyboard from JSON.
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

    # -----------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------

    @staticmethod
    def save_plan(
        plan: VideoAssemblyPlan,
        output_file: str | Path,
    ) -> Path:
        """
        Save the assembly plan as JSON.
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
    ) -> VideoAssemblyPlan:
        """
        Load an assembly plan from JSON.
        """

        path = Path(
            plan_file
        )

        if not path.exists():
            raise FileNotFoundError(
                f"Video assembly plan not found: {path}"
            )

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        return VideoAssemblyPlan.model_validate(
            data
        )

    # -----------------------------------------------------------------
    # File validation
    # -----------------------------------------------------------------

    @staticmethod
    def _validate_image_file(
        image_path: Path,
    ) -> str:
        """
        Validate a generated image file.

        Returns:
            "ready" when valid.
            "missing" when absent.
            "invalid" when empty or not a file.
        """

        if not image_path.exists():
            return "missing"

        if not image_path.is_file():
            return "invalid"

        if image_path.stat().st_size <= 0:
            return "invalid"

        return "ready"

    @staticmethod
    def _validate_audio_file(
        audio_file: str | Path | None,
    ) -> str | None:
        """
        Validate an optional audio file.

        Actual audio/video synchronization is handled
        in a later milestone.
        """

        if audio_file is None:
            return None

        path = Path(
            audio_file
        )

        if not path.exists():
            raise FileNotFoundError(
                f"Audio file not found: {path}"
            )

        if not path.is_file():
            raise ValueError(
                f"Audio path is not a file: {path}"
            )

        if path.stat().st_size <= 0:
            raise ValueError(
                f"Audio file is empty: {path}"
            )

        return str(path)

    # -----------------------------------------------------------------
    # Plan validation
    # -----------------------------------------------------------------

    @staticmethod
    def _validate_plan(
        plan: VideoAssemblyPlan,
        storyboard: Storyboard,
    ) -> None:
        """
        Validate the completed assembly plan.
        """

        if plan.topic != storyboard.topic:
            raise ValueError(
                "Video plan topic does not match "
                "the storyboard topic."
            )

        if not plan.clips:
            raise ValueError(
                "Video assembly plan contains no clips."
            )

        if len(plan.clips) != len(
            storyboard.scenes
        ):
            raise ValueError(
                "Video clip count does not match "
                "storyboard scene count."
            )

        previous_end = 0.0

        for index, (
            clip,
            scene,
        ) in enumerate(
            zip(
                plan.clips,
                storyboard.scenes,
            )
        ):
            if clip.scene_id != scene.scene_id:
                raise ValueError(
                    "Video clip scene ordering mismatch "
                    f"at index {index}."
                )

            if abs(
                clip.start_seconds
                - scene.start_seconds
            ) > 0.01:
                raise ValueError(
                    f"{clip.scene_id} start time does not "
                    "match storyboard."
                )

            if abs(
                clip.duration_seconds
                - scene.duration_seconds
            ) > 0.01:
                raise ValueError(
                    f"{clip.scene_id} duration does not "
                    "match storyboard."
                )

            if index > 0:
                if abs(
                    clip.start_seconds
                    - previous_end
                ) > 0.01:
                    raise ValueError(
                        f"{clip.scene_id} is not sequentially "
                        "aligned with the previous clip."
                    )

            previous_end = (
                clip.start_seconds
                + clip.duration_seconds
            )

        expected_duration = sum(
            scene.duration_seconds
            for scene in storyboard.scenes
        )

        if abs(
            plan.total_duration_seconds
            - expected_duration
        ) > 0.01:
            raise ValueError(
                "Video plan duration does not match "
                "storyboard duration."
            )