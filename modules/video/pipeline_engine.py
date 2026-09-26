from pathlib import Path
import inspect
import os
import shutil
import json
import time
from collections.abc import Mapping

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
from modules.video.pilot_qa import PilotVideoQA
from modules.qa.engine import record_stage_qa
from modules.qa.models import QAStageResult, QAStatus


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
        image_reviewer=None,
        image_provider=None,
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
        self.image_reviewer = image_reviewer
        self.image_provider = image_provider

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
        enable_image_ai_qa: bool = False,
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
            enable_image_ai_qa=enable_image_ai_qa,
        )

    def run(
        self,
        request: VideoProductionRequest,
    ) -> VideoProductionResult:
        """
        Execute the complete video-production workflow.
        """

        image_ai_status: QAStatus | None = None
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

            project_directory = self._project_directory(request.storyboard_file)
            if request.enable_image_ai_qa:
                current_stage = "image_ai_qa"
                image_ai_status = self._review_and_repair_images(
                    request,
                    project_directory,
                )

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

            record_stage_qa(
                project_directory,
                QAStageResult(
                    stage="technical_qa",
                    status=technical.status,
                    checks=technical.checks,
                    findings=technical.issues,
                    reviewer="deterministic",
                ),
            )

            if technical.status in {"FAIL", "REVIEW"} and self._has_sync_failures(technical.checks):
                state.start("synchronization")
                save_pipeline_state(state, state_file)
                synchronized_plan = self._build_synchronized_plan(request, video_plan)
                self.assembly_engine.save_plan(synchronized_plan, synchronized_plan_file)
                state.complete("synchronization")
                state.start("motion")
                save_pipeline_state(state, state_file)
                motion_plan = self._build_motion_plan(request, synchronized_plan)
                self.motion_engine.save_plan(motion_plan, motion_plan_file)
                state.complete("motion")
                state.start("render")
                save_pipeline_state(state, state_file)
                rendered_file = self.renderer.render(
                    assembly_plan=synchronized_plan,
                    motion_plan=motion_plan,
                    audio_file=audio_path,
                    output_file=output_video_file,
                )
                state.complete("render")
                state.start("technical_qa")
                technical = PilotVideoQA().run_technical(
                    storyboard,
                    synchronized_plan,
                    audio_path,
                    rendered_file,
                )
                if technical.status == "PASS":
                    state.complete("technical_qa")
                else:
                    state.fail("technical_qa", "Sync QA still fails after one automatic repair.")
                save_pipeline_state(state, state_file)
                record_stage_qa(
                    project_directory,
                    QAStageResult(
                        stage="sync_repair",
                        status="PASS" if technical.status == "PASS" else technical.status,
                        checks=technical.checks,
                        findings=technical.issues,
                        recommendations=[] if technical.status == "PASS" else [
                            "Automatic resynchronization retry did not resolve the issue; stop for diagnosis."
                        ],
                    ),
                )
                record_stage_qa(
                    project_directory,
                    QAStageResult(
                        stage="technical_qa",
                        status=technical.status,
                        checks=technical.checks,
                        findings=technical.issues,
                        reviewer="deterministic",
                    ),
                )

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
                error_message=(
                    "Image/editorial QA failed; inspect qa/qa_report.json before approval."
                    if image_ai_status == "FAIL"
                    else "Technical QA did not pass after the bounded synchronization repair; inspect qa/qa_report.json."
                    if technical.status != "PASS"
                    else None
                ),
                technical_qa_status=technical.status,
                image_ai_qa_status=image_ai_status,
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
                image_ai_qa_status=image_ai_status,
                approval_status="PENDING",
            )

    @staticmethod
    def _project_directory(storyboard_file: str | Path) -> Path:
        storyboard_directory = Path(storyboard_file).resolve().parent
        return (
            storyboard_directory.parent
            if storyboard_directory.name == "storyboard"
            else storyboard_directory
        )

    @staticmethod
    def _has_sync_failures(checks: Mapping[str, QAStatus]) -> bool:
        return any(
            checks.get(name) == "FAIL"
            for name in (
                "no_gaps_or_overlaps",
                "duration_consistency",
                "timestamp_coverage",
                "video",
            )
        ) or checks.get("timeline_drift") in {"REVIEW", "FAIL"}

    def _review_and_repair_images(
        self,
        request: VideoProductionRequest,
        project_directory: Path,
    ) -> QAStatus:
        from modules.image.character_profile import load_character_profile
        from modules.image.models import ImageGenerationRequest
        from modules.image.prompt_builder import ImagePromptBuilder
        from modules.storyboard.engine import StoryboardEngine
        from modules.video.pilot_qa import OpenAIImageEditorialReviewer, _validate_png

        storyboard_path = Path(request.storyboard_file)
        storyboard = StoryboardEngine.load_storyboard(storyboard_path)
        image_directory = Path(request.image_directory)
        reviewer = self.image_reviewer or OpenAIImageEditorialReviewer()
        scenes = list(storyboard.scenes)
        first_reviews = {}

        def editorial_candidates(index: int) -> list[dict[str, str]]:
            return [
                {"scene_id": scenes[candidate_index].scene_id,
                 "narration": scenes[candidate_index].narration}
                for candidate_index in range(max(0, index - 1), min(len(scenes), index + 2))
            ]

        def review_scene(index: int):
            review_method = reviewer.review
            parameters = inspect.signature(review_method).parameters
            kwargs = {}
            if "editorial_candidates" in parameters:
                kwargs["editorial_candidates"] = editorial_candidates(index)
            return review_method(
                image_directory / f"{scenes[index].scene_id}.png",
                scenes[index],
                **kwargs,
            )

        for index in range(len(scenes)):
            first_reviews[index] = review_scene(index)

        moves: dict[int, int] = {}
        unresolved_editorial: list[str] = []
        for index, review in first_reviews.items():
            if review.editorial_context not in {"FAIL", "REVIEW"} or not scenes[index].text_overlay:
                continue
            suggested_id = review.suggested_editorial_scene_id
            if not suggested_id:
                continue
            target_index = next(
                (candidate for candidate, scene in enumerate(scenes) if scene.scene_id == suggested_id),
                None,
            )
            if target_index is None or abs(target_index - index) != 1:
                unresolved_editorial.append(
                    f"{scenes[index].scene_id}: no valid adjacent placement recommendation."
                )
                continue
            if scenes[target_index].text_overlay:
                unresolved_editorial.append(
                    f"{scenes[index].scene_id}: suggested target {suggested_id} already has editorial text."
                )
                continue
            trial_positions = [
                target_index if scene_index == index else scene_index
                for scene_index, scene in enumerate(scenes)
                if scene.text_overlay
            ]
            trial_positions.sort()
            if any(not 3 <= right - left <= 4 for left, right in zip(trial_positions, trial_positions[1:])):
                unresolved_editorial.append(
                    f"{scenes[index].scene_id}: moving the callout would break the 3-4-scene cadence."
                )
                continue
            moves[index] = target_index

        affected_indices: set[int] = set()
        for index, target_index in moves.items():
            word = scenes[index].text_overlay
            scenes[index] = scenes[index].model_copy(update={"text_overlay": ""})
            scenes[target_index] = scenes[target_index].model_copy(update={"text_overlay": word})
            affected_indices.update({index, target_index})

        for index, review in first_reviews.items():
            has_actionable_image_finding = any(
                status != "PASS"
                for status in (
                    review.status,
                    review.narration_image,
                    review.narration_description,
                    review.editorial_context,
                )
            )
            if (
                review.status == "FAIL"
                or review.narration_image == "FAIL"
                or review.narration_description == "FAIL"
                or (has_actionable_image_finding and bool(review.correction_prompt))
            ):
                affected_indices.add(index)
            if (
                review.editorial_context == "FAIL"
                and index not in moves
                and index not in affected_indices
            ):
                unresolved_editorial.append(f"{scenes[index].scene_id}: editorial placement remains unresolved.")

        prompt_builder = ImagePromptBuilder(
            character_profile=load_character_profile(project_directory)
        )
        for index in affected_indices:
            scenes[index] = scenes[index].model_copy(
                update={"image_prompt": prompt_builder.build(scenes[index])}
            )

        if affected_indices:
            initial_checks = {
                f"{scenes[review_index].scene_id}.{check_name}": getattr(first_review, check_name)
                for review_index, first_review in first_reviews.items()
                for check_name in (
                    "narration_image",
                    "narration_description",
                    "editorial_context",
                )
            }
            initial_status: QAStatus = (
                "FAIL"
                if any(first_review.status == "FAIL" for first_review in first_reviews.values())
                or any(value == "FAIL" for value in initial_checks.values())
                else "REVIEW"
                if any(first_review.status == "REVIEW" for first_review in first_reviews.values())
                else "PASS"
            )
            record_stage_qa(
                project_directory,
                QAStageResult(
                    stage="image_editorial_qa",
                    status=initial_status,
                    checks=initial_checks,
                    findings=[
                        f"{scenes[review_index].scene_id}: {first_review.rationale}"
                        for review_index, first_review in first_reviews.items()
                        if first_review.status != "PASS"
                    ],
                    recommendations=["Applying bounded automatic image/editorial corrections."],
                    reviewer="openai_vision",
                ),
            )

        retries: dict[int, str] = {}
        repair_root = project_directory / "qa" / "image_repair"
        repair_root.mkdir(parents=True, exist_ok=True)
        previous_attempts = [
            int(path.name.removeprefix("attempt_"))
            for path in repair_root.glob("attempt_*")
            if path.is_dir() and path.name.removeprefix("attempt_").isdigit()
        ]
        attempt_directory = repair_root / f"attempt_{max(previous_attempts, default=0) + 1}"
        for index in sorted(affected_indices):
            scene = scenes[index]
            original_path = image_directory / f"{scene.scene_id}.png"
            review = first_reviews.get(index)
            correction = review.correction_prompt if review else None
            if not correction:
                correction = (
                    "Correct the visible mismatch with the scene narration and visual description. "
                    "Keep the established character, hand-drawn style, and requested editorial word accurate."
                )
            correction_prompt = f"{scene.image_prompt} Image QA correction: {correction}"
            candidate_directory = attempt_directory / "candidates"
            candidate_directory.mkdir(parents=True, exist_ok=True)
            provider = self.image_provider
            if provider is None:
                from modules.image.providers.openai import OpenAIImageProvider

                provider = OpenAIImageProvider()
            result = provider.generate(
                ImageGenerationRequest(
                    image_id=scene.scene_id,
                    scene_id=scene.scene_id,
                    prompt=correction_prompt,
                    output_directory=str(candidate_directory),
                )
            )
            if result.status != "completed" or not result.file_path:
                raise RuntimeError(
                    f"Automatic image repair failed for {scene.scene_id}: {result.error_message or 'no image returned'}"
                )
            candidate_path = Path(result.file_path)
            _validate_png(candidate_path)
            if original_path.is_file():
                originals_directory = attempt_directory / "originals"
                originals_directory.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original_path, originals_directory / original_path.name)
            os.replace(candidate_path, original_path)
            scenes[index] = scene.model_copy(update={"image_prompt": correction_prompt})
            retries[index] = correction_prompt

        if affected_indices:
            updated_storyboard = storyboard.model_copy(update={"scenes": scenes})
            StoryboardEngine.save_storyboard(updated_storyboard, storyboard_path)
            manifest_path = image_directory / "image_manifest.json"
            if manifest_path.is_file():
                from modules.image.batch import ImageBatchEngine

                assets = ImageBatchEngine.load_manifest(manifest_path)
                by_scene_id = {asset.scene_id: index for index, asset in enumerate(assets)}
                for index, prompt in retries.items():
                    scene = scenes[index]
                    asset_index = by_scene_id.get(scene.scene_id)
                    if asset_index is not None:
                        assets[asset_index] = assets[asset_index].model_copy(
                            update={"prompt": prompt, "file_path": str(image_directory / f"{scene.scene_id}.png"), "status": "completed"}
                        )
                ImageBatchEngine.save_manifest(assets, manifest_path)

        retry_reviews = {
            index: review_scene(index)
            for index in sorted(affected_indices)
        }
        final_reviews = dict(first_reviews)
        final_reviews.update(retry_reviews)
        unresolved = list(unresolved_editorial)
        for index, review in final_reviews.items():
            if review.status == "FAIL" or review.narration_image == "FAIL" or review.narration_description == "FAIL" or review.editorial_context == "FAIL":
                unresolved.append(f"{scenes[index].scene_id}: {review.rationale}")

        status = "FAIL" if unresolved else "REVIEW" if any(review.status == "REVIEW" for review in final_reviews.values()) else "PASS"
        checks = {
            f"{scenes[index].scene_id}.narration_image": review.narration_image
            for index, review in final_reviews.items()
        }
        checks.update({
            f"{scenes[index].scene_id}.narration_description": review.narration_description
            for index, review in final_reviews.items()
        })
        checks.update({
            f"{scenes[index].scene_id}.editorial_context": review.editorial_context
            for index, review in final_reviews.items()
        })
        record_stage_qa(
            project_directory,
            QAStageResult(
                stage="image_editorial_qa",
                status=status,
                checks=checks,
                findings=unresolved + [
                    f"{scenes[index].scene_id}: {review.rationale}"
                    for index, review in final_reviews.items()
                    if review.status == "REVIEW"
                ],
                recommendations=[] if status == "PASS" else [
                    "Inspect the preserved originals and QA report before approval."
                ],
                reviewer="openai_vision",
            ),
        )
        if status == "FAIL":
            raise RuntimeError("Image/editorial QA still fails after one targeted regeneration; inspect qa/qa_report.json.")
        return status

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