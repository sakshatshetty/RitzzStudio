"""Set the generated thumbnail on an already uploaded private test video."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.project.manager import ProjectManager
from modules.publishing.engine import PublishingEngine
from modules.publishing.youtube_provider import YouTubeProvider


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    projects_directory = Path("projects")
    manager = ProjectManager(projects_directory)
    project = manager.load_project(project_id)
    project_directory = manager.get_project_path(project)
    publishing_directory = project_directory / "publishing"
    thumbnail_file = project_directory / "video" / "thumbnail.jpg"
    result_file = publishing_directory / "publish.json"
    marker_file = publishing_directory / "thumbnail_upload.json"
    if not result_file.is_file():
        raise FileNotFoundError(
            f"Video publish result is missing: {result_file}"
        )
    publish_result = PublishingEngine.load_publish_result(project_directory)
    if not publish_result.video_id.strip():
        raise ValueError(f"Saved publish result has no YouTube video ID: {result_file}")
    if marker_file.is_file():
        marker = json.loads(marker_file.read_text(encoding="utf-8"))
        if marker.get("status") == "completed":
            if marker.get("video_id") != publish_result.video_id:
                raise RuntimeError(
                    "Saved thumbnail upload marker belongs to a different video ID."
                )
            print(f"Thumbnail already uploaded for video {publish_result.video_id}.")
            return 0
    if not thumbnail_file.is_file() or thumbnail_file.stat().st_size == 0:
        raise FileNotFoundError(
            f"Generated thumbnail is missing or empty: {thumbnail_file}"
        )

    provider = YouTubeProvider(
        Path(os.environ["GOOGLE_CLIENT_SECRETS_FILE"]),
        Path(os.environ["GOOGLE_TOKEN_FILE"]),
    )
    response = provider.set_thumbnail(
        video_id=publish_result.video_id,
        thumbnail_file=thumbnail_file,
    )
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_marker = marker_file.with_suffix(".json.tmp")
    temporary_marker.write_text(
        json.dumps(
            {
                "status": "completed",
                "video_id": publish_result.video_id,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "response": response,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary_marker.replace(marker_file)
    print(f"Thumbnail uploaded for {publish_result.url}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
