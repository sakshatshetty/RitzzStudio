from pathlib import Path

from modules.video.engine import (
    VideoAssemblyEngine,
)

from modules.video.motion_engine import (
    VideoMotionEngine,
)

from modules.video.render_engine import (
    FFmpegVideoRenderer,
)

from modules.video.models import (
    VideoAssemblyPlan,
)

from modules.video.motion_models import (
    VideoMotionPlan,
)

from modules.video.pipeline_models import (
    VideoProductionRequest,
    VideoProductionResult,
)

from modules.video.sync_engine import (
    VideoSynchronizationEngine,
)


class VideoProductionPipeline:
    """
    Runs the complete Ritzz video-production workflow.

    Current workflow:

        Storyboard
            ↓
        Video Assembly
            ↓
        Audio Synchronization
            ↓
        Motion Planning
            ↓
        FFmpeg Rendering
            ↓
        Final MP4

    This milestone handles orchestration only.
    Individual engines remain responsible for their
    own processing and validation.
    """

    VIDEO_PLAN_FILENAME = (
        "video_plan.json"
    )

    SYNCHRONIZED_PLAN_FILENAME = (
        "synced_video_plan.json"
    )

    MOTION_PLAN_FILENAME = (
        "motion_plan.json"
    )

    DEFAULT_OUTPUT_FILENAME = (
        "ritzz_final.mp4"
    )

    def __init__(
        self,
        assembly_engine: VideoAssemblyEngine | None = None,
        synchronization_engine: (
            VideoSynchronizationEngine | None
        ) = None,
        motion_engine: VideoMotionEngine | None = None,
        renderer: FFmpegVideoRenderer | None = None,
    ) -> None:
        self.assembly_engine = (
            assembly_engine
            or VideoAssemblyEngine()
        )

        self.synchronization_engine = (
            synchronization_engine
            or VideoSynchronizationEngine()
        )

        self.motion_engine = (
            motion_engine
            or VideoMotionEngine()
        )

        self.renderer = (
            renderer
            or FFmpegVideoRenderer()
        )

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def create_request(
        self,
        storyboard_file: str | Path,
        image_directory: str | Path,
        narration_result_file: str | Path,
        output_directory: str | Path,
        audio_file: str | Path | None = None,
        output_video_file: str | Path | None = None,
    ) -> VideoProductionRequest:
        """
        Create a typed production request.
        """

        return VideoProductionRequest(
            storyboard_file=str(
                storyboard_file
            ),
            image_directory=str(
                image_directory
            ),
            narration_result_file=str(
                narration_result_file
            ),
            audio_file=(
                str(audio_file)
                if audio_file is not None
                else None
            ),
            output_directory=str(
                output_directory
            ),
            output_video_file=(
                str(output_video_file)
                if output_video_file is not None
                else None
            ),
        )

    def run(
        self,
        request: VideoProductionRequest,
    ) -> VideoProductionResult:
        """
        Execute the complete video-production workflow.
        """

        try:
            output_directory = Path(
                request.output_directory
            )

            output_directory.mkdir(
                parents=True,
                exist_ok=True,
            )

            video_plan = (
                self._build_assembly_plan(
                    request
                )
            )

            video_plan_file = (
                output_directory
                / self.VIDEO_PLAN_FILENAME
            )

            self.assembly_engine.save_plan(
                video_plan,
                video_plan_file,
            )

            audio_path = (
                Path(request.audio_file)
                if request.audio_file
                else self._get_audio_path(
                    video_plan
                )
            )

            synchronized_plan = (
                self._build_synchronized_plan(
                    request=request,
                    video_plan=video_plan,
                )
            )

            synchronized_plan_file = (
                output_directory
                / self.SYNCHRONIZED_PLAN_FILENAME
            )

            self.assembly_engine.save_plan(
                synchronized_plan,
                synchronized_plan_file,
            )

            motion_plan = (
                self._build_motion_plan(
                    request=request,
                    synchronized_plan=(
                        synchronized_plan
                    ),
                )
            )

            motion_plan_file = (
                output_directory
                / self.MOTION_PLAN_FILENAME
            )

            self.motion_engine.save_plan(
                motion_plan,
                motion_plan_file,
            )

            output_video_file = (
                Path(
                    request.output_video_file
                )
                if request.output_video_file
                else output_directory
                / self.DEFAULT_OUTPUT_FILENAME
            )

            rendered_file = (
                self.renderer.render(
                    assembly_plan=synchronized_plan,
                    motion_plan=motion_plan,
                    audio_file=audio_path,
                    output_file=(
                        output_video_file
                    ),
                )
            )

            return VideoProductionResult(
                status="completed",
                video_plan_file=str(
                    video_plan_file
                ),
                synchronized_plan_file=str(
                    synchronized_plan_file
                ),
                motion_plan_file=str(
                    motion_plan_file
                ),
                output_video_file=str(
                    rendered_file
                ),
                scene_count=len(
                    synchronized_plan.clips
                ),
                duration_seconds=(
                    synchronized_plan
                    .total_duration_seconds
                ),
                error_message=None,
            )

        except Exception as exc:
            return VideoProductionResult(
                status="failed",
                video_plan_file=None,
                synchronized_plan_file=None,
                motion_plan_file=None,
                output_video_file=None,
                scene_count=0,
                duration_seconds=0,
                error_message=str(exc),
            )

    # -----------------------------------------------------------------
    # Pipeline stages
    # -----------------------------------------------------------------

    def _build_assembly_plan(
        self,
        request: VideoProductionRequest,
    ) -> VideoAssemblyPlan:
        """
        Stage 1:
        Build the initial assembly plan.
        """

        storyboard = (
            self.assembly_engine.load_storyboard(
                request.storyboard_file
            )
        )

        audio_file = (
            request.audio_file
            if request.audio_file
            else None
        )

        return self.assembly_engine.create_plan(
            storyboard=storyboard,
            image_directory=request.image_directory,
            audio_file=audio_file,
        )

    def _build_synchronized_plan(
        self,
        request: VideoProductionRequest,
        video_plan: VideoAssemblyPlan,
    ) -> VideoAssemblyPlan:
        """
        Stage 2:
        Synchronize the video timeline with
        actual ElevenLabs narration timestamps.
        """

        storyboard = (
            self.assembly_engine.load_storyboard(
                request.storyboard_file
            )
        )

        alignment = (
            self.synchronization_engine
            .load_narration_alignment(
                request.narration_result_file
            )
        )

        return (
            self.synchronization_engine
            .synchronize_plan(
                storyboard=storyboard,
                assembly_plan=video_plan,
                alignment=alignment,
            )
        )

    def _build_motion_plan(
        self,
        request: VideoProductionRequest,
        synchronized_plan: VideoAssemblyPlan,
    ) -> VideoMotionPlan:
        """
        Stage 3:
        Build zoom/pan instructions based on
        storyboard camera-motion settings.
        """

        storyboard = (
            self.assembly_engine.load_storyboard(
                request.storyboard_file
            )
        )

        return self.motion_engine.create_plan(
            storyboard=storyboard,
            assembly_plan=synchronized_plan,
        )

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _get_audio_path(
        video_plan: VideoAssemblyPlan,
    ) -> Path:
        """
        Resolve audio path from the assembly plan.
        """

        if not video_plan.audio_path:
            raise ValueError(
                "No audio file was provided and "
                "the assembly plan has no audio path."
            )

        return Path(
            video_plan.audio_path
        )