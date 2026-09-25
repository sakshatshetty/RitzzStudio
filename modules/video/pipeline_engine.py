from pathlib import Path
import struct
import zlib
import json
import time

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
    PipelineStageName,
    VideoProductionRequest,
    VideoProductionResult,
)

from modules.video.sync_engine import (
    VideoSynchronizationEngine,
)
from modules.video.pipeline_state import load_pipeline_state, save_pipeline_state
from modules.storyboard.models import Storyboard
from modules.video.pilot_qa import PilotVideoQA


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

    STATE_FILENAME = "pipeline_state.json"
    USAGE_FILENAME = "pipeline_usage.json"
    STAGE_ORDER = ["asset_validation", "assembly", "synchronization", "motion", "render", "technical_qa"]

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
        resume: bool = True,
        retry_from_stage: PipelineStageName | None = None,
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
            resume=resume,
            retry_from_stage=retry_from_stage,
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
            state_file = output_directory / self.STATE_FILENAME
            state = load_pipeline_state(state_file) if request.resume else load_pipeline_state(output_directory / "__new_state.json")
            usage_file = output_directory / self.USAGE_FILENAME
            usage = json.loads(usage_file.read_text(encoding="utf-8")) if usage_file.exists() and request.resume else {"stages": []}
            if request.retry_from_stage:
                state.reset_from(request.retry_from_stage, self.STAGE_ORDER)
                self._remove_downstream_artifacts(output_directory, request.retry_from_stage)
            usage.setdefault("stages", [])
            current_stage = "asset_validation"
            usage["stages"].append({"stage": current_stage, "started_at": time.time()})
            self._validate_assets(request)
            self._save_usage(usage, usage_file, current_stage)

            video_plan_file = output_directory / self.VIDEO_PLAN_FILENAME
            current_stage = "assembly"
            usage["stages"].append({"stage": current_stage, "started_at": time.time()})
            state.start(current_stage)
            save_pipeline_state(state, state_file)
            video_plan = self._load_or_build_plan(request, video_plan_file, self._build_assembly_plan)
            state.complete("assembly")
            save_pipeline_state(state, state_file)
            self._save_usage(usage, usage_file, "assembly")

            self.assembly_engine.save_plan(video_plan, video_plan_file)

            audio_path = (
                Path(request.audio_file)
                if request.audio_file
                else self._get_audio_path(
                    video_plan
                )
            )

            synchronized_plan_file = output_directory / self.SYNCHRONIZED_PLAN_FILENAME
            current_stage = "synchronization"
            usage["stages"].append({"stage": current_stage, "started_at": time.time()})
            state.start(current_stage)
            save_pipeline_state(state, state_file)
            synchronized_plan = self._load_or_build_plan(
                request, synchronized_plan_file,
                lambda item: self._build_synchronized_plan(item, video_plan),
            )
            state.complete("synchronization")
            save_pipeline_state(state, state_file)
            self._save_usage(usage, usage_file, "synchronization")

            self.assembly_engine.save_plan(
                synchronized_plan,
                synchronized_plan_file,
            )

            motion_plan_file = output_directory / self.MOTION_PLAN_FILENAME
            current_stage = "motion"
            usage["stages"].append({"stage": current_stage, "started_at": time.time()})
            state.start(current_stage)
            save_pipeline_state(state, state_file)
            motion_plan = self._load_or_build_motion(request, motion_plan_file, synchronized_plan)
            state.complete("motion")
            save_pipeline_state(state, state_file)
            self._save_usage(usage, usage_file, "motion")

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

            current_stage = "render"
            usage["stages"].append({"stage": current_stage, "started_at": time.time()})
            state.start(current_stage)
            save_pipeline_state(state, state_file)
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
            state.complete("render")
            save_pipeline_state(state, state_file)
            self._save_usage(usage, usage_file, "render")

            current_stage = "technical_qa"
            usage["stages"].append({"stage": current_stage, "started_at": time.time()})
            state.start(current_stage)
            storyboard = self.assembly_engine.load_storyboard(request.storyboard_file)
            technical = PilotVideoQA().run_technical(
                storyboard,
                synchronized_plan,
                audio_path,
                rendered_file,
            )
            state.complete(current_stage) if technical.status == "PASS" else state.fail(current_stage, technical.status)
            save_pipeline_state(state, state_file)
            self._save_usage(usage, usage_file, "technical_qa")

            return VideoProductionResult(
                status="completed" if technical.status == "PASS" else "failed",
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
                technical_qa_status=technical.status,
                approval_status="PENDING",
            )

        except Exception as exc:
            try:
                state.fail(locals().get("current_stage", "pipeline"), str(exc))
                save_pipeline_state(state, state_file)
                self._save_usage(usage, usage_file, locals().get("current_stage", "pipeline"), error=str(exc))
            except (UnboundLocalError, NameError):
                pass
            return VideoProductionResult(
                status="failed",
                video_plan_file=None,
                synchronized_plan_file=None,
                motion_plan_file=None,
                output_video_file=None,
                scene_count=0,
                duration_seconds=0,
                error_message=str(exc),
                technical_qa_status="FAIL",
                approval_status="PENDING",
            )

    @staticmethod
    def _load_or_build_plan(request, path, builder):
        if request.resume and Path(path).exists():
            return VideoAssemblyEngine.load_plan(path)
        plan = builder(request)
        return plan

    def _load_or_build_motion(self, request, path, synchronized_plan):
        if request.resume and Path(path).exists():
            return self.motion_engine.load_plan(path)
        return self._build_motion_plan(request, synchronized_plan)

    @staticmethod
    def _validate_assets(request: VideoProductionRequest) -> None:
        image_dir = Path(request.image_directory)
        if not image_dir.is_dir():
            raise FileNotFoundError(f"Image directory not found: {image_dir}")
        storyboard = VideoAssemblyEngine.load_storyboard(request.storyboard_file)
        missing = []
        for scene in storyboard.scenes:
            image = image_dir / f"{scene.scene_id}.png"
            if not image.is_file() or image.stat().st_size == 0:
                missing.append(str(image))
                continue
            data = image.read_bytes()
            if data[:8] != b"\x89PNG\r\n\x1a\n":
                missing.append(f"{image} (invalid PNG)")
        audio = Path(request.audio_file) if request.audio_file else None
        if audio is not None and (not audio.is_file() or audio.stat().st_size == 0):
            raise FileNotFoundError(f"Audio file not found or empty: {audio}")
        if missing:
            raise ValueError("Asset validation failed: " + "; ".join(missing))

    @staticmethod
    def _save_usage(usage: dict, path: Path, stage: str, error: str | None = None) -> None:
        for item in reversed(usage.get("stages", [])):
            if item.get("stage") == stage and "duration_seconds" not in item:
                item["duration_seconds"] = round(max(0, time.time() - item["started_at"]), 3)
                if error:
                    item["error"] = error
                break
        path.write_text(json.dumps(usage, indent=2), encoding="utf-8")

    @staticmethod
    def _remove_downstream_artifacts(output_directory: Path, stage: str) -> None:
        files = {
            "assembly": ["video_plan.json", "synced_video_plan.json", "motion_plan.json", "ritzz_final.mp4"],
            "synchronization": ["synced_video_plan.json", "motion_plan.json", "ritzz_final.mp4"],
            "motion": ["motion_plan.json", "ritzz_final.mp4"],
            "render": ["ritzz_final.mp4"],
            "technical_qa": [],
            "asset_validation": [],
        }
        for name in files.get(stage, []):
            (output_directory / name).unlink(missing_ok=True)

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