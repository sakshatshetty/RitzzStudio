"""Upload an approved test video privately through the existing M6 publisher."""

import hashlib
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.production_state import ProductionStateStore
from modules.project.manager import ProjectManager
from modules.project.packaging import PackagingArtifact
from modules.publishing.engine import PublishingEngine
from modules.publishing.video_validation import validate_upload_master
from modules.publishing.youtube_provider import YouTubeProvider
from modules.video.render_engine import FFmpegVideoRenderer


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as video:
        for block in iter(lambda: video.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_upload_summary(
    upload: dict,
    summary_file: str | None,
) -> None:
    if not summary_file:
        return
    master = upload.get("upload_details") or {}
    video = master.get("local_master") or {}
    processing_status = upload.get(
        "youtube_processing_status",
        "YOUTUBE_PROCESSING_UNVERIFIED",
    )
    lines = [
        "## YouTube upload quality",
        "",
        "**LOCAL MASTER**",
        (
            f"{video.get('width', 'unknown')}x{video.get('height', 'unknown')} / "
            f"{video.get('fps', 'unknown')} FPS / "
            f"{video.get('video_codec', 'unknown')} / "
            f"{video.get('video_bitrate_bps', 'unknown')} bps"
        ),
        f"File: `{master.get('file_path', 'not recorded')}`",
        f"SHA-256: `{master.get('sha256', 'not recorded')}`",
        "",
        "**YOUTUBE**",
        f"Upload: {upload.get('upload_status', 'unknown')}",
        f"Video ID: `{upload.get('video_id', 'unknown')}`",
        f"Processing: {processing_status}",
    ]
    processing_error = upload.get("youtube_processing_error")
    if processing_error:
        lines.append(f"Processing detail: {processing_error}")
    with Path(summary_file).open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines) + "\n")


def _persist_production_upload(upload: dict) -> None:
    production_id = os.environ.get("RITZZ_PRODUCTION_ID")
    if (
        not production_id
        or upload.get("upload_status") != "UPLOAD_COMPLETE"
        or not upload.get("uploaded_at")
        or not upload.get("upload_details")
    ):
        return
    artifact_root = Path(
        os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts")
    )
    ProductionStateStore(
        artifact_root / "production_state.json",
        artifact_root,
    ).record_youtube_upload(upload)


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    projects_directory = Path("projects")
    manager = ProjectManager(projects_directory)
    project = manager.load_project(project_id)
    project_directory = manager.get_project_path(project)
    video_file = project_directory / "video" / "ritzz_test.mp4"
    packaging_file = project_directory / "packaging.json"
    saved_publish_result = project_directory / "publishing" / "publish.json"
    if saved_publish_result.is_file():
        saved_result = json.loads(
            saved_publish_result.read_text(encoding="utf-8")
        )
        if saved_result.get("publish_status") == "PRIVATE" and saved_result.get("video_id"):
            _persist_production_upload(saved_result)
            _write_upload_summary(
                saved_result,
                os.environ.get("GITHUB_STEP_SUMMARY"),
            )
            print(
                "LOCAL MASTER: "
                f"{(saved_result.get('upload_details') or {}).get('local_master', {})}"
            )
            print(
                "YOUTUBE: "
                f"{saved_result.get('upload_status', 'UPLOAD_COMPLETE')}; "
                f"processing={saved_result.get('youtube_processing_status', 'YOUTUBE_PROCESSING_UNVERIFIED')}"
            )
            print(
                "Private video upload already completed for "
                f"{saved_result['video_id']}; skipping video upload."
            )
            return 0
    if not video_file.is_file() or not packaging_file.is_file():
        raise FileNotFoundError("Rendered test video or packaging artifact is missing.")

    artifact = PackagingArtifact.from_dict(
        json.loads(packaging_file.read_text(encoding="utf-8"))
    )
    renderer = FFmpegVideoRenderer()
    local_master = validate_upload_master(
        video_file,
        probe_media=renderer._probe_media,
        target_bitrate_bps=renderer.video_bitrate_bps,
    )
    upload_details = {
        "file_path": video_file.relative_to(project_directory).as_posix(),
        "sha256": _file_sha256(video_file),
        "local_master": local_master,
    }
    approved_by = os.environ.get("GITHUB_ACTOR", "github-actions-reviewer")
    credentials_file = Path(os.environ["GOOGLE_CLIENT_SECRETS_FILE"])
    token_file = Path(os.environ["GOOGLE_TOKEN_FILE"])
    provider = YouTubeProvider(credentials_file, token_file)
    engine = PublishingEngine(projects_directory, provider=provider)
    engine.create_approval(project, approved=True, approved_by=approved_by)
    result = engine.publish_packaged_video(
        project=project,
        video_file=video_file,
        artifact=artifact,
        approved_by=approved_by,
        category=os.environ.get("RITZZ_YOUTUBE_CATEGORY", "Entertainment"),
        language="en",
        made_for_kids=False,
        upload_details=upload_details,
    )
    processing = provider.get_video_processing_status(result.video_id)
    result.youtube_processing_status = processing["processing_status"]
    result.youtube_processing_error = processing.get(
        "processing_error",
        processing.get("verification_error"),
    )
    result.youtube_details = processing
    PublishingEngine._write_json_atomically(
        saved_publish_result,
        result.to_dict(),
    )
    upload_state = {
        "video_id": result.video_id,
        "upload_status": result.upload_status,
        "uploaded_at": result.uploaded_at,
        "file_path": upload_details["file_path"],
        "sha256": upload_details["sha256"],
        "upload_details": upload_details,
        "local_master": local_master,
        "youtube_processing_status": result.youtube_processing_status,
        "youtube_processing_error": result.youtube_processing_error,
        "youtube_details": result.youtube_details,
    }
    _persist_production_upload(upload_state)
    _write_upload_summary(
        result.to_dict(),
        os.environ.get("GITHUB_STEP_SUMMARY"),
    )
    print(
        "LOCAL MASTER: "
        f"{local_master['width']}x{local_master['height']} / "
        f"{local_master['fps']} FPS / {local_master['video_codec']} / "
        f"{local_master['video_bitrate_bps']} bps"
    )
    print(
        f"YOUTUBE: upload={result.upload_status}; "
        f"video_id={result.video_id}; "
        f"processing={result.youtube_processing_status}"
    )
    print(json.dumps(result.to_dict(), indent=2))
    if result.publish_status != "PRIVATE":
        raise RuntimeError("Test upload did not remain private.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
