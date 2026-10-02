"""Upload an approved test video privately through the existing M6 publisher."""

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.project.manager import ProjectManager
from modules.project.packaging import PackagingArtifact
from modules.publishing.engine import PublishingEngine
from modules.publishing.youtube_provider import YouTubeProvider


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
    )
    print(json.dumps(result.to_dict(), indent=2))
    if result.publish_status != "PRIVATE":
        raise RuntimeError("Test upload did not remain private.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
