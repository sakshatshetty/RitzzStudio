"""Render and technically validate the approved test project."""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.image.image_overlays import create_thumbnail
from modules.project.manager import ProjectManager
from modules.project.packaging import PackagingArtifact
from modules.qa.engine import record_stage_qa
from modules.qa.models import QAStageResult
from modules.storyboard.engine import StoryboardEngine
from modules.video.engine import VideoAssemblyEngine
from modules.video.pilot_qa import OpenAIImageEditorialReviewer, PilotVideoQA
from modules.video.pipeline_engine import VideoProductionPipeline


def _validate_production_render_format(probe: dict[str, object]) -> None:
    width = probe.get("width")
    height = probe.get("height")
    fps = probe.get("fps")
    if (
        not isinstance(width, int)
        or not isinstance(height, int)
        or width != 1920
        or height != 1080
        or width * 9 != height * 16
    ):
        raise RuntimeError(
            "Production render must be exactly 1920x1080 with a 16:9 aspect ratio; "
            f"received {width}x{height}."
        )
    if not isinstance(fps, (int, float)) or isinstance(fps, bool) or fps != 30.0:
        raise RuntimeError(
            f"Production render must be exactly 30 FPS; received {fps}."
        )


def _reject_semantic_qa_fail(status: str) -> None:
    if status == "FAIL":
        raise RuntimeError(
            "Rendered-video semantic QA found a clear scene/narration or editorial mismatch."
        )


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    project_manager = ProjectManager(Path("projects"))
    project = project_manager.load_project(project_id)
    project_directory = project_manager.get_project_path(project)
    storyboard_file = project_directory / "storyboard" / "storyboard_audio_timed.json"
    image_directory = project_directory / "images"
    narration_result_file = project_directory / "voice" / "narration_result.json"
    audio_file = project_directory / "voice" / "narration.mp3"
    output_directory = project_directory / "video"
    output_video_file = output_directory / "ritzz_test.mp4"

    pipeline = VideoProductionPipeline()
    request = pipeline.create_request(
        storyboard_file=storyboard_file,
        image_directory=image_directory,
        narration_result_file=narration_result_file,
        audio_file=audio_file,
        output_directory=output_directory,
        output_video_file=output_video_file,
        resume=True,
        enable_image_ai_qa=False,
    )
    result = pipeline.run(request)
    print(f"Render status: {result.status}")
    print(f"Technical QA: {result.technical_qa_status}")
    print(f"Output: {result.output_video_file}")
    if result.status != "completed" or result.technical_qa_status != "PASS":
        raise RuntimeError(result.error_message or "Render or technical QA failed.")

    render_probe = pipeline.renderer._probe_media(output_video_file)
    _validate_production_render_format(render_probe)
    print("Production render format: 1920x1080, 16:9, 30 FPS")

    if not result.synchronized_plan_file:
        raise RuntimeError("Render completed without a synchronized scene plan.")
    storyboard = StoryboardEngine.load_storyboard(storyboard_file)
    plan = VideoAssemblyEngine.load_plan(result.synchronized_plan_file)
    semantic = PilotVideoQA().run_rendered_video_semantic(
        storyboard,
        plan,
        output_video_file,
        OpenAIImageEditorialReviewer(),
    )
    semantic_report_file = project_directory / "qa" / "rendered_video_semantic_qa.json"
    semantic_report_file.parent.mkdir(parents=True, exist_ok=True)
    semantic_report_file.write_text(
        semantic.model_dump_json(indent=2),
        encoding="utf-8",
    )
    record_stage_qa(
        project_directory,
        QAStageResult(
            stage="rendered_semantic_qa",
            status=semantic.status,
            checks={
                result.scene_id: result.status
                for result in semantic.results
            },
            findings=[
                f"{result.scene_id}: {result.rationale}"
                for result in semantic.results
                if result.status != "PASS"
            ],
            recommendations=[
                "Inspect the rendered video and scene report before human approval."
            ] if semantic.status != "PASS" else [],
            reviewer="openai_vision_rendered_frames",
        ),
    )
    print(f"Rendered-video semantic QA: {semantic.status}")
    print(f"Semantic QA report: {semantic_report_file}")
    print(f"Semantic QA counts: {json.dumps(semantic.counts, sort_keys=True)}")
    _reject_semantic_qa_fail(semantic.status)

    packaging_file = project_directory / "packaging.json"
    artifact = PackagingArtifact.from_dict(
        json.loads(packaging_file.read_text(encoding="utf-8"))
    )
    thumbnail_file = project_directory / "video" / "thumbnail.jpg"
    create_thumbnail(
        image_directory / f"{storyboard.scenes[0].scene_id}.png",
        thumbnail_file,
        artifact.selected_title,
    )
    print(f"Generated YouTube thumbnail: {thumbnail_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
