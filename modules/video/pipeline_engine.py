import hashlib
import json
import os
import shutil
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise
from pathlib import Path
from typing import Any, ClassVar

from modules.project.config import ProductionConfig
from modules.qa.engine import record_stage_qa
from modules.qa.models import QAStageResult, QAStatus
from modules.video.engine import (
    VideoAssemblyEngine,
)
from modules.video.models import (
    VideoAssemblyPlan,
)
from modules.video.motion_engine import (
    VideoMotionEngine,
)
from modules.video.motion_models import (
    VideoMotionPlan,
)
from modules.video.pilot_qa import PilotVideoQA
from modules.video.pipeline_models import (
    PipelineStageName,
    VideoProductionRequest,
    VideoProductionResult,
)
from modules.video.pipeline_state import load_pipeline_state, save_pipeline_state
from modules.video.qa_models import SceneQAResult, TechnicalQAResult
from modules.video.render_engine import (
    FFmpegVideoRenderer,
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

    STATE_FILENAME = "pipeline_state.json"
    USAGE_FILENAME = "pipeline_usage.json"
    MAX_QA_REPAIR_ATTEMPTS = 3
    STAGE_ORDER: ClassVar[list[str]] = [
        "asset_validation",
        "assembly",
        "synchronization",
        "motion",
        "render",
        "technical_qa",
    ]

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
            self._validate_assets(
                request,
                allow_image_repair=request.enable_image_ai_qa,
            )
            self._save_usage(usage, usage_file, current_stage)

            project_directory = self._project_directory(request.storyboard_file)
            if request.enable_image_ai_qa:
                current_stage = "image_ai_qa"
                image_ai_status = self._review_and_repair_images(
                    request,
                    project_directory,
                )
                if image_ai_status == "FAIL":
                    raise RuntimeError(
                        f"Image semantic QA status was {image_ai_status}; "
                        "video assembly cannot proceed. Review qa/qa_report.json."
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

            storyboard = self.assembly_engine.load_storyboard(request.storyboard_file)
            rendered_file: Path | None = None
            technical: TechnicalQAResult | None = None
            for qa_attempt in range(1, self.MAX_QA_REPAIR_ATTEMPTS + 1):
                current_stage = "render"
                usage["stages"].append(
                    {"stage": current_stage, "started_at": time.time()}
                )
                state.start(current_stage)
                save_pipeline_state(state, state_file)
                rendered_file = self.renderer.render(
                    assembly_plan=synchronized_plan,
                    motion_plan=motion_plan,
                    audio_file=audio_path,
                    output_file=output_video_file,
                )
                self._save_usage(usage, usage_file, "render")

                current_stage = "technical_qa"
                usage["stages"].append(
                    {"stage": current_stage, "started_at": time.time()}
                )
                state.start(current_stage)
                save_pipeline_state(state, state_file)
                technical = PilotVideoQA().run_technical(
                    storyboard,
                    synchronized_plan,
                    audio_path,
                    rendered_file,
                    production_config=ProductionConfig.model_validate_json(
                        (project_directory / "production_config.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    if (project_directory / "production_config.json").is_file()
                    else ProductionConfig(),
                )
                record_stage_qa(
                    project_directory,
                    QAStageResult(
                        stage="technical_qa",
                        status=technical.status,
                        checks=technical.checks,
                        findings=technical.issues,
                        reviewer="deterministic",
                        attempt=qa_attempt,
                    ),
                )
                self._save_usage(usage, usage_file, "technical_qa")
                if technical.status == "PASS":
                    if qa_attempt > 1:
                        record_stage_qa(
                            project_directory,
                            QAStageResult(
                                stage="technical_qa_repair",
                                status="PASS",
                                checks=technical.checks,
                                findings=technical.issues,
                                recommendations=[],
                                attempt=qa_attempt - 1,
                            ),
                        )
                    state.complete("technical_qa")
                    state.complete("render")
                    save_pipeline_state(state, state_file)
                    break

                if qa_attempt == self.MAX_QA_REPAIR_ATTEMPTS:
                    state.fail(
                        "technical_qa",
                        "Technical QA did not pass after "
                        f"{self.MAX_QA_REPAIR_ATTEMPTS} repair-and-render attempts.",
                    )
                    state.fail(
                        "render",
                        "Render cannot complete until technical QA passes.",
                    )
                    save_pipeline_state(state, state_file)
                    break

                repair_recommendations = [
                    "Repair the reported technical QA issues and rerender."
                ]
                if technical.checks.get("audio_loudness") != "PASS":
                    audio_adjustments = (
                        self.renderer.adjust_audio_filter_from_measurement(
                            integrated_lufs=technical.integrated_lufs,
                            true_peak_dbtp=technical.true_peak_dbtp,
                            loudness_tolerance_lu=(
                                PilotVideoQA.LOUDNESS_TOLERANCE_LU
                            ),
                            true_peak_tolerance_db=(
                                PilotVideoQA.TRUE_PEAK_MEASUREMENT_TOLERANCE_DB
                            ),
                        )
                    )
                    repair_recommendations = audio_adjustments or [
                        "Audio QA could not provide a measurable value to adjust; "
                        + "rerendering once before reporting any unresolved finding."
                    ]
                record_stage_qa(
                    project_directory,
                    QAStageResult(
                        stage="technical_qa_repair",
                        status=technical.status,
                        checks=technical.checks,
                        findings=technical.issues,
                        recommendations=repair_recommendations,
                        attempt=qa_attempt,
                    ),
                )
                if self._has_sync_failures(technical.checks):
                    state.start("synchronization")
                    save_pipeline_state(state, state_file)
                    synchronized_plan = self._build_synchronized_plan(
                        request,
                        video_plan,
                    )
                    self.assembly_engine.save_plan(
                        synchronized_plan,
                        synchronized_plan_file,
                    )
                    state.complete("synchronization")
                    state.start("motion")
                    save_pipeline_state(state, state_file)
                    motion_plan = self._build_motion_plan(
                        request,
                        synchronized_plan,
                    )
                    self.motion_engine.save_plan(motion_plan, motion_plan_file)
                    state.complete("motion")
                    save_pipeline_state(state, state_file)
            assert technical is not None
            assert rendered_file is not None

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
                    "Technical QA did not pass after "
                    f"{self.MAX_QA_REPAIR_ATTEMPTS} repair-and-render attempts; "
                    "inspect qa/qa_report.json."
                    if technical.status != "PASS"
                    else None
                ),
                technical_qa_status=technical.status,
                integrated_lufs=technical.integrated_lufs,
                true_peak_dbtp=technical.true_peak_dbtp,
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
        repair_attempt: int = 1,
        cached_reviews: dict[str, dict] | None = None,
        usage_metrics: dict[str, int | float] | None = None,
    ) -> QAStatus:
        from modules.image.character_profile import load_character_profile
        from modules.image.models import ImageGenerationRequest
        from modules.image.prompt_builder import ImagePromptBuilder
        from modules.storyboard.engine import StoryboardEngine
        from modules.storyboard.visual_context import load_visual_world_bible
        from modules.video.image_asset_qa import (
            duplicate_scene_findings,
            expected_image_size,
            inspect_image_asset,
        )
        from modules.video.pilot_qa import OpenAISemanticReviewer, _validate_png
        from modules.video.sync_engine import VideoSynchronizationEngine

        storyboard_path = Path(request.storyboard_file)
        storyboard = StoryboardEngine.load_storyboard(storyboard_path)
        image_directory = Path(request.image_directory)
        visual_world = load_visual_world_bible(project_directory)
        reviewer = self.image_reviewer or OpenAISemanticReviewer(
            visual_world=visual_world
        )
        scenes = list(storyboard.scenes)
        first_reviews: dict[int, SceneQAResult] = {}
        usage_metrics = usage_metrics if usage_metrics is not None else {
            "ai_reviewed_scenes": 0,
            "ai_batch_count": 0,
            "ai_retry_count": 0,
            "images_regenerated": 0,
            "deterministic_checked": 0,
            "deterministic_failed": 0,
            "started_monotonic": time.monotonic(),
        }
        cache_file = project_directory / "qa" / "image_semantic_cache.json"
        if cached_reviews is None:
            if cache_file.is_file():
                cache_document = json.loads(cache_file.read_text(encoding="utf-8"))
                if (
                    not isinstance(cache_document, dict)
                    or cache_document.get("version") != 1
                    or not isinstance(cache_document.get("scenes"), dict)
                ):
                    raise ValueError(f"Invalid semantic QA cache: {cache_file}")
                cached_reviews = cache_document["scenes"]
            else:
                cached_reviews = {}
        if not isinstance(cached_reviews, dict):
            raise ValueError("Semantic QA cache entries must be a scene-keyed object.")
        cache_file.parent.mkdir(parents=True, exist_ok=True)

        scene_ids = [scene.scene_id for scene in scenes]
        structure_issues: list[str] = []
        if len(set(scene_ids)) != len(scene_ids):
            structure_issues.append("QA_INPUT_INVALID: duplicate scene IDs in storyboard.")
        if any(
            not scene.scene_id.startswith("scene_")
            or not scene.narration.strip()
            or not scene.visual_description.strip()
            or not scene.image_prompt.strip()
            for scene in scenes
        ):
            structure_issues.append(
                "QA_INPUT_INVALID: scene ID, full narration, visual description, or image prompt is missing."
            )
        if visual_world:
            contract_ids = [
                scene.visual_contract.scene_id
                for scene in scenes
                if scene.visual_contract is not None
            ]
            if (
                len(contract_ids) != len(scenes)
                or contract_ids != scene_ids
            ):
                structure_issues.append(
                    "QA_INPUT_INVALID: project visual-world bible requires one matching visual contract per scene."
                )
        if any(
            right.start_seconds < left.start_seconds
            for left, right in pairwise(scenes)
        ):
            structure_issues.append("QA_INPUT_INVALID: storyboard scenes are not in timestamp order.")
        alignment = VideoSynchronizationEngine.load_narration_alignment(
            request.narration_result_file
        )
        compact_narration = "".join(
            VideoSynchronizationEngine._compact_text(scene.narration)
            for scene in scenes
        )
        compact_alignment = VideoSynchronizationEngine._compact_text(
            "".join(alignment.characters)
        )
        if compact_narration != compact_alignment:
            structure_issues.append(
                "QA_INPUT_INVALID: concatenated full scene narration does not exactly cover the narration alignment."
            )
        if structure_issues:
            record_stage_qa(
                project_directory,
                QAStageResult(
                    stage="image_semantic_qa",
                    status="FAIL",
                    findings=structure_issues,
                    recommendations=[
                        "Repair the storyboard or narration-alignment input before semantic QA; no image was regenerated."
                    ],
                    details={"failure_class": "input_data"},
                    reviewer="deterministic",
                    attempt=repair_attempt,
                ),
            )
            return "FAIL"

        expected_width, expected_height = expected_image_size()
        image_findings: dict[int, str] = {}
        image_hashes: list[int | None] = []
        for index, scene in enumerate(scenes):
            usage_metrics["deterministic_checked"] += 1
            image_path = image_directory / f"{scene.scene_id}.png"
            try:
                inspection = inspect_image_asset(image_path)
                if (
                    inspection.width != expected_width
                    or inspection.height != expected_height
                    or inspection.width * 9 != inspection.height * 16
                ):
                    raise ValueError(
                        f"expected {expected_width}x{expected_height} 16:9 PNG; "
                        f"received {inspection.width}x{inspection.height}"
                    )
                image_hashes.append(inspection.difference_hash)
            except (OSError, ValueError) as exc:
                image_hashes.append(None)
                image_findings[index] = (
                    f"{scene.scene_id}: deterministic image check failed: {exc}"
                )
        try:
            similarity_threshold = float(
                os.getenv("RITZZ_QA_IMAGE_SIMILARITY_THRESHOLD", "0.97")
            )
            duplicate_window = int(
                os.getenv("RITZZ_QA_NEAR_DUPLICATE_WINDOW", "2")
            )
        except ValueError as exc:
            raise ValueError(
                "QA image similarity threshold/window configuration is invalid."
            ) from exc
        duplicate_findings = duplicate_scene_findings(
            scene_ids,
            image_hashes,
            threshold=similarity_threshold,
            window=duplicate_window,
        )
        for index, finding in duplicate_findings.items():
            image_findings[index] = finding
        usage_metrics["deterministic_failed"] += len(image_findings)

        def review_scene(index: int):
            return reviewer.review(
                image_directory / f"{scenes[index].scene_id}.png",
                scenes[index],
            )

        def cache_key(index: int) -> str:
            image_path = image_directory / f"{scenes[index].scene_id}.png"
            payload = {
                "semantic_qa_policy_version": 3,
                "reviewer": (
                    f"{type(reviewer).__module__}.{type(reviewer).__qualname__}:"
                    f"{getattr(reviewer, 'model', 'default')}"
                ),
                "scene": scenes[index].model_dump(
                    include={
                        "scene_id",
                        "narration",
                        "visual_description",
                        "image_prompt",
                        "visual_contract",
                    }
                ),
                "visual_world": (
                    visual_world.model_dump(mode="json")
                    if visual_world is not None
                    else None
                ),
            }
            digest = hashlib.sha256(image_path.read_bytes())
            digest.update(json.dumps(payload, sort_keys=True).encode("utf-8"))
            return digest.hexdigest()

        def save_review_cache() -> None:
            temporary_cache = cache_file.with_suffix(".tmp")
            temporary_cache.write_text(
                json.dumps(
                    {"version": 1, "scenes": cached_reviews},
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            temporary_cache.replace(cache_file)

        def review_scenes(indexes: list[int]) -> dict[int, SceneQAResult]:
            if not indexes:
                return {}
            batch_method = getattr(reviewer, "review_batch", None)
            if not callable(batch_method):
                results = {
                    index: review_scene(index)
                    for index in indexes
                }
                if not all(
                    isinstance(result, SceneQAResult)
                    for result in results.values()
                ):
                    raise TypeError(
                        "Semantic QA reviewer returned an invalid scene result."
                    )
                usage_metrics["ai_reviewed_scenes"] += len(indexes)
                return results
            try:
                batch_size = int(os.getenv(
                    "RITZZ_SEMANTIC_QA_BATCH_SIZE",
                    os.getenv("SEMANTIC_QA_BATCH_SIZE", "4"),
                ))
                concurrency = int(os.getenv("RITZZ_SEMANTIC_QA_CONCURRENCY", "2"))
                batch_retries = int(os.getenv("RITZZ_SEMANTIC_QA_BATCH_RETRIES", "1"))
            except ValueError as exc:
                raise ValueError("Semantic QA batch settings must be positive integers.") from exc
            if batch_size < 1 or concurrency < 1 or batch_retries < 0:
                raise ValueError("Semantic QA batch settings must be positive integers.")
            concurrency = min(concurrency, 4)
            batches = [
                indexes[offset:offset + batch_size]
                for offset in range(0, len(indexes), batch_size)
            ]
            items_by_batch: list[list[tuple[Path, Any]]] = [
                [
                    (image_directory / f"{scenes[index].scene_id}.png", scenes[index])
                    for index in batch
                ]
                for batch in batches
            ]

            def run_batch(items: list[tuple[Path, Any]]) -> list[SceneQAResult]:
                for attempt in range(batch_retries + 1):
                    try:
                        results = batch_method(items)
                        if not isinstance(results, list) or not all(
                            isinstance(result, SceneQAResult)
                            for result in results
                        ):
                            raise TypeError(
                                "Semantic QA batch returned invalid scene results."
                            )
                        return results
                    except Exception as exc:
                        if attempt >= batch_retries:
                            raise RuntimeError(
                                "Semantic QA batch failed after "
                                f"{attempt + 1} attempt(s): "
                                f"{[scene.scene_id for _, scene in items]}"
                            ) from exc
                        usage_metrics["ai_retry_count"] += 1
                        time.sleep(min(1.0, 0.25 * (attempt + 1)))
                raise RuntimeError("Semantic QA batch retry loop ended unexpectedly.")

            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                batch_results = list(executor.map(run_batch, items_by_batch))
            usage_metrics["ai_batch_count"] += len(batches)
            usage_metrics["ai_reviewed_scenes"] += len(indexes)
            return {
                index: result
                for batch, results in zip(batches, batch_results, strict=True)
                for index, result in zip(batch, results, strict=True)
            }

        pending_reviews: list[int] = []
        for index, scene in enumerate(scenes):
            if index in image_findings:
                first_reviews[index] = SceneQAResult(
                    scene_id=scene.scene_id,
                    status="FAIL",
                    narration_image="FAIL",
                    narration_description="PASS",
                    rationale=image_findings[index],
                    correction_prompt=image_findings[index],
                )
                continue
            fingerprint = cache_key(index)
            saved = cached_reviews.get(scene.scene_id)
            if (
                isinstance(saved, dict)
                and saved.get("fingerprint") == fingerprint
                and isinstance(saved.get("result"), dict)
            ):
                cached_result = SceneQAResult.model_validate(saved["result"])
                if cached_result.status == "PASS":
                    first_reviews[index] = cached_result
                    continue
            if (
                visual_world is not None
                and scene.visual_contract is not None
                and not scene.visual_contract.semantic_review_reasons
            ):
                first_reviews[index] = SceneQAResult(
                    scene_id=scene.scene_id,
                    status="PASS",
                    narration_image="PASS",
                    narration_description="PASS",
                    rationale=(
                        "The scene contract requires no targeted semantic review; "
                        "deterministic asset and timeline checks passed."
                    ),
                )
                continue
            pending_reviews.append(index)
        first_reviews.update(review_scenes(pending_reviews))
        for index, review in first_reviews.items():
            if review.status == "PASS":
                cached_reviews[scenes[index].scene_id] = {
                    "fingerprint": cache_key(index),
                    "result": review.model_dump(mode="json"),
                }
        save_review_cache()

        affected_indices: set[int] = set()
        manual_review_findings: list[str] = []
        suggested_fixes: dict[int, str] = {}
        for index, review in first_reviews.items():
            review_statuses = (
                review.status,
                review.narration_image,
                review.narration_description,
            )
            has_clear_failure = any(status == "FAIL" for status in review_statuses)
            has_actionable_review = (
                any(status == "REVIEW" for status in review_statuses)
                and bool((review.correction_prompt or "").strip())
            )
            needs_visual_repair = has_clear_failure or has_actionable_review
            has_unresolved_issue = any(
                status in {"FAIL", "REVIEW"} for status in review_statuses
            )
            if needs_visual_repair:
                affected_indices.add(index)
                correction = (review.correction_prompt or "").strip()
                if not correction and has_clear_failure:
                    correction = (
                        f"Correct the clear QA mismatch: {review.rationale}. "
                        "Make the scene visibly match its narration and visual description, "
                        "while preserving the established character and illustration style."
                    )
                if correction:
                    suggested_fixes[index] = correction
            elif has_unresolved_issue:
                manual_review_findings.append(
                    f"{scenes[index].scene_id}: no actionable image correction was "
                    "supplied, so the original image was preserved for review."
                )
        prompt_builder = ImagePromptBuilder(
            character_profile=load_character_profile(project_directory),
            visual_world=visual_world,
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
                    stage="image_semantic_qa",
                    status=initial_status,
                    checks=initial_checks,
                    findings=[
                        f"{scenes[review_index].scene_id}: {first_review.rationale}"
                        for review_index, first_review in first_reviews.items()
                        if first_review.status != "PASS"
                    ],
                    recommendations=[
                        f"{scenes[index].scene_id}: proposed fix — {correction}"
                        for index, correction in suggested_fixes.items()
                    ] or ["Applying bounded automatic image corrections."],
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
        repair_history_path = project_directory / "qa" / "visual_repair_history.json"
        if repair_history_path.is_file():
            repair_history = json.loads(
                repair_history_path.read_text(encoding="utf-8")
            )
            if (
                not isinstance(repair_history, dict)
                or repair_history.get("version") != 1
                or not isinstance(repair_history.get("scenes"), dict)
            ):
                raise ValueError(f"Invalid visual repair history: {repair_history_path}")
        else:
            repair_history = {"version": 1, "scenes": {}}

        failure_strategies = {
            "ANACHRONISM": (
                "Remove objects, materials, clothing, infrastructure, and technology "
                "that exceed the project technology ceiling."
            ),
            "AMBIGUITY": (
                "Follow the scene contract's explicit ambiguity resolution; do not "
                "substitute another meaning of the ambiguous term."
            ),
            "WRONG_ACTION": (
                "Show the scene contract's stated action clearly and make the action "
                "the primary focal point."
            ),
            "WRONG_ENVIRONMENT": (
                "Rebuild the setting from the project visual world and scene environment "
                "instead of using a generic or modern setting."
            ),
            "MISSING_REQUIRED_OBJECT": (
                "Make every required object in the scene contract clearly visible and "
                "recognizable."
            ),
            "FORBIDDEN_OBJECT": (
                "Exclude every object prohibited by the project world and scene contract."
            ),
            "CHARACTER_CONTINUITY": (
                "Restore the recurring character or object identity and continuity "
                "requirements without repeating the old composition."
            ),
            "NARRATION_MISMATCH": (
                "Depict the scene's visual contract and action, not a different idea "
                "from nearby narration."
            ),
            "VISUAL_DUPLICATE": (
                "Use a clearly different viewpoint, composition, subject placement, "
                "action, and environmental emphasis while remaining faithful to the contract."
            ),
        }

        def save_repair_history() -> None:
            temporary_history = repair_history_path.with_suffix(".tmp")
            temporary_history.write_text(
                json.dumps(repair_history, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temporary_history.replace(repair_history_path)

        for index in sorted(affected_indices):
            scene = scenes[index]
            original_path = image_directory / f"{scene.scene_id}.png"
            review = first_reviews.get(index)
            correction = suggested_fixes.get(index)
            category = (
                review.failure_category
                if review and review.failure_category
                else "VISUAL_DUPLICATE"
                if review and "perceptually similar" in review.rationale
                else "OTHER"
            )
            if not correction:
                correction = (
                    f"Correct this image QA finding: {review.rationale}. "
                    if review
                    else ""
                ) + (
                    "Correct the visible mismatch with the scene narration and visual description. "
                    "Keep the established character, hand-drawn style, and scene meaning accurate."
                )
            strategy = failure_strategies.get(
                category,
                "Correct the specific reviewer finding while satisfying the full visual contract.",
            )
            prompt_fingerprint = hashlib.sha256(
                f"{scene.image_prompt}\n{category}\n{correction}\n{strategy}".encode("utf-8")
            ).hexdigest()
            scene_history = repair_history["scenes"].setdefault(
                scene.scene_id,
                {"attempts": []},
            )
            if not isinstance(scene_history, dict) or not isinstance(
                scene_history.get("attempts"), list
            ):
                raise ValueError(
                    f"Invalid repair-history entry for {scene.scene_id}."
                )
            previous_fingerprints = {
                entry.get("prompt_sha256")
                for entry in scene_history["attempts"]
                if isinstance(entry, dict)
            }
            if prompt_fingerprint in previous_fingerprints:
                strategy += (
                    " Avoid repeating any earlier failed visual solution; choose an "
                    "alternative composition and make the correction unmistakable."
                )
                prompt_fingerprint = hashlib.sha256(
                    f"{prompt_fingerprint}\n{repair_attempt}\n{strategy}".encode("utf-8")
                ).hexdigest()
            correction_prompt = (
                f"{scene.image_prompt} Image QA correction category: {category}. "
                f"Finding: {correction} Repair strategy: {strategy}"
            )
            repair_record = {
                "repair_attempt": repair_attempt,
                "failure_category": category,
                "finding": review.rationale if review else correction,
                "correction": correction,
                "prompt_sha256": prompt_fingerprint,
                "verification": None,
            }
            scene_history["attempts"].append(repair_record)
            save_repair_history()
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
            inspection = inspect_image_asset(candidate_path)
            if (
                inspection.width != expected_width
                or inspection.height != expected_height
                or inspection.width * 9 != inspection.height * 16
            ):
                raise RuntimeError(
                    f"Repair for {scene.scene_id} produced "
                    f"{inspection.width}x{inspection.height}; expected "
                    f"{expected_width}x{expected_height}."
                )
            if original_path.is_file():
                originals_directory = attempt_directory / "originals"
                originals_directory.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original_path, originals_directory / original_path.name)
            os.replace(candidate_path, original_path)
            scenes[index] = scene.model_copy(update={"image_prompt": correction_prompt})
            retries[index] = correction_prompt
            usage_metrics["images_regenerated"] += 1

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

        retry_reviews = review_scenes(sorted(affected_indices))
        final_reviews = dict(first_reviews)
        final_reviews.update(retry_reviews)
        for index, review in retry_reviews.items():
            scene_history = repair_history["scenes"].get(scenes[index].scene_id)
            if isinstance(scene_history, dict):
                attempts = scene_history.get("attempts")
            else:
                attempts = None
            latest_attempt = (
                attempts[-1]
                if isinstance(attempts, list) and attempts
                else None
            )
            if isinstance(latest_attempt, dict):
                latest_attempt["verification"] = {
                    "status": review.status,
                    "failure_category": review.failure_category,
                    "rationale": review.rationale,
                }
            if review.status == "PASS":
                cached_reviews[scenes[index].scene_id] = {
                    "fingerprint": cache_key(index),
                    "result": review.model_dump(mode="json"),
                }
        save_review_cache()
        if affected_indices:
            save_repair_history()
        final_hashes: list[int | None] = []
        remaining_image_findings: dict[int, str] = {}
        for index, scene in enumerate(scenes):
            image_path = image_directory / f"{scene.scene_id}.png"
            try:
                inspection = inspect_image_asset(image_path)
                if (
                    inspection.width != expected_width
                    or inspection.height != expected_height
                    or inspection.width * 9 != inspection.height * 16
                ):
                    raise ValueError(
                        f"expected {expected_width}x{expected_height} 16:9 PNG; "
                        f"received {inspection.width}x{inspection.height}"
                    )
                final_hashes.append(inspection.difference_hash)
            except (OSError, ValueError) as exc:
                final_hashes.append(None)
                remaining_image_findings[index] = (
                    f"{scene.scene_id}: deterministic image check failed after repair: {exc}"
                )
        remaining_duplicate_findings = duplicate_scene_findings(
            scene_ids,
            final_hashes,
            threshold=similarity_threshold,
            window=duplicate_window,
        )
        remaining_image_findings.update(remaining_duplicate_findings)
        for index, finding in remaining_image_findings.items():
            final_reviews[index] = SceneQAResult(
                scene_id=scenes[index].scene_id,
                status="FAIL",
                narration_image="FAIL",
                narration_description="PASS",
                rationale=finding,
                correction_prompt=finding,
            )
            if index not in affected_indices:
                affected_indices.add(index)
                suggested_fixes[index] = finding
        unresolved: list[str] = []
        for index, review in final_reviews.items():
            if any(
                check_status == "FAIL"
                for check_status in (
                    review.status,
                    review.narration_image,
                    review.narration_description,
                )
            ):
                unresolved.append(f"{scenes[index].scene_id}: {review.rationale}")

        final_check_statuses = [
            check_status
            for review in final_reviews.values()
            for check_status in (
                review.status,
                review.narration_image,
                review.narration_description,
            )
        ]
        status: QAStatus = (
            "FAIL"
            if unresolved or "FAIL" in final_check_statuses
            else "REVIEW"
            if "REVIEW" in final_check_statuses
            else "PASS"
        )
        checks: dict[str, QAStatus] = {
            f"{scenes[index].scene_id}.file_check": (
                "FAIL" if index in remaining_image_findings else "PASS"
            )
            for index in range(len(scenes))
        }
        checks.update({
            f"{scenes[index].scene_id}.image_readability": (
                "FAIL" if index in remaining_image_findings else "PASS"
            )
            for index in range(len(scenes))
        })
        checks.update({
            f"{scenes[index].scene_id}.dimension_check": (
                "FAIL" if index in remaining_image_findings else "PASS"
            )
            for index in range(len(scenes))
        })
        checks.update({
            f"{scenes[index].scene_id}.duplicate_check": (
                "FAIL" if index in remaining_duplicate_findings else "PASS"
            )
            for index in range(len(scenes))
        })
        checks.update({
            f"{scenes[index].scene_id}.narration_input": "PASS"
            for index in range(len(scenes))
        })
        checks.update({
            f"{scenes[index].scene_id}.narration_image": review.narration_image
            for index, review in final_reviews.items()
        })
        checks.update({
            f"{scenes[index].scene_id}.narration_description": review.narration_description
            for index, review in final_reviews.items()
        })
        checks.update({
            f"{scenes[index].scene_id}.visual_intent_match": (
                review.narration_description
            )
            for index, review in final_reviews.items()
        })
        record_stage_qa(
            project_directory,
            QAStageResult(
                stage="image_semantic_qa",
                status=status,
                checks=checks,
                findings=unresolved + manual_review_findings + [
                    f"{scenes[index].scene_id}: {review.rationale}"
                    for index, review in final_reviews.items()
                    if any(
                        check_status != "PASS"
                        for check_status in (
                            review.status,
                            review.narration_image,
                            review.narration_description,
                        )
                    )
                ],
                reviewer="openai_vision",
                attempt=repair_attempt,
                metrics={
                    "total_scenes": len(scenes),
                    "deterministic_checked": int(usage_metrics["deterministic_checked"]),
                    "deterministic_failed": int(usage_metrics["deterministic_failed"]),
                    "ai_reviewed_scenes": int(usage_metrics["ai_reviewed_scenes"]),
                    "ai_batches": int(usage_metrics["ai_batch_count"]),
                    "ai_retries": int(usage_metrics["ai_retry_count"]),
                    "images_regenerated": int(usage_metrics["images_regenerated"]),
                    "final_passed": sum(
                        review.status == "PASS" for review in final_reviews.values()
                    ),
                    "requiring_review": sum(
                        review.status == "REVIEW" for review in final_reviews.values()
                    ),
                    "failed_scenes": sum(
                        review.status == "FAIL" for review in final_reviews.values()
                    ),
                    "elapsed_seconds": round(
                        time.monotonic() - float(usage_metrics["started_monotonic"]),
                        3,
                    ),
                },
                details={
                    "failure_class": (
                        "image_asset"
                        if remaining_image_findings
                        else "semantic"
                        if status != "PASS"
                        else "none"
                    ),
                    "semantic_model": getattr(reviewer, "model", "custom"),
                },
                recommendations=(
                    [
                        f"{scenes[index].scene_id}: proposed fix — {correction}"
                        for index, correction in suggested_fixes.items()
                    ]
                    if status != "PASS" and suggested_fixes
                    else ["Inspect the preserved originals and QA report before approval."]
                    if status != "PASS"
                    else []
                ),
            ),
        )
        if (
            status != "PASS"
            and affected_indices
            and repair_attempt < self.MAX_QA_REPAIR_ATTEMPTS
        ):
            return self._review_and_repair_images(
                request,
                project_directory,
                repair_attempt=repair_attempt + 1,
                cached_reviews=cached_reviews,
                usage_metrics=usage_metrics,
            )
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
    def _validate_assets(
        request: VideoProductionRequest,
        *,
        allow_image_repair: bool = False,
    ) -> None:
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
            with image.open("rb") as image_stream:
                signature = image_stream.read(8)
            if signature != b"\x89PNG\r\n\x1a\n":
                missing.append(f"{image} (invalid PNG)")
        audio = Path(request.audio_file) if request.audio_file else None
        if audio is not None and (not audio.is_file() or audio.stat().st_size == 0):
            raise FileNotFoundError(f"Audio file not found or empty: {audio}")
        if missing and not allow_image_repair:
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