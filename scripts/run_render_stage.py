"""Render and technically validate the approved test project."""

import os
from pathlib import Path

from modules.project.manager import ProjectManager
from modules.video.pipeline_engine import VideoProductionPipeline


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
