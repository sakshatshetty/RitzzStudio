from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

from modules.project.manager import ProjectManager
from modules.project.packaging import PackagingArtifact, PackagingEngine
from modules.publishing.engine import PublishingEngine
from modules.publishing.youtube_provider import YouTubeProvider

load_dotenv(PROJECT_ROOT / ".env")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build final packaging metadata and upload the chosen video to YouTube with your manual schedule."
    )
    parser.add_argument("--project-id", type=str, help="Existing project ID to update and upload.")
    parser.add_argument("--title", type=str, help="Exact selected title to upload. Overrides the title index.")
    parser.add_argument("--title-index", type=int, default=None, help="Index of the title option to select (0-based).")
    parser.add_argument("--topic", type=str, help="Topic used to generate packaging if a packaging artifact does not exist.")
    parser.add_argument("--script-excerpt", type=str, help="Script excerpt used to generate packaging metadata if missing.")
    parser.add_argument("--video-file", type=str, required=True, help="Path to the final video file to upload.")
    parser.add_argument("--category", type=str, default="Entertainment", help="YouTube category, e.g. Entertainment or Education.")
    parser.add_argument("--language", type=str, default="en", help="Video language code, default en.")
    parser.add_argument("--made-for-kids", action="store_true", help="Set the made-for-kids audience flag.")
    parser.add_argument("--schedule", type=str, help="Manual YouTube schedule timestamp in ISO-8601 format, e.g. 2026-10-02T12:00:00+00:00.")
    parser.add_argument("--approved-by", type=str, required=True, help="Reviewer identity recorded in the approval artifact.")
    parser.add_argument("--create-approval", action="store_true", help="Create the approval artifact for the selected reviewer before upload.")
    parser.add_argument("--projects-dir", type=str, default=str(PROJECT_ROOT / "projects"), help="Projects directory.")
    return parser


def _load_or_build_packaging(project_manager: ProjectManager, packaging_engine: PackagingEngine, project, *, topic: str, script_excerpt: str) -> PackagingArtifact:
    project_path = project_manager.get_project_path(project)
    packaging_path = project_path / "packaging.json"
    if packaging_path.exists():
        return PackagingArtifact.from_dict(json.loads(packaging_path.read_text(encoding="utf-8")))

    if not topic or not script_excerpt:
        raise ValueError("A topic and script excerpt are required when no packaging artifact exists yet.")

    return packaging_engine.build_project_packaging(
        project=project,
        topic=topic,
        script_excerpt=script_excerpt,
    )


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if not args.project_id:
        parser.error("--project-id is required.")

    projects_dir = Path(args.projects_dir)
    project_manager = ProjectManager(projects_dir)
    try:
        project = project_manager.load_project(args.project_id)
    except FileNotFoundError:
        parser.error(f"Project ID not found: {args.project_id}")

    packaging_engine = PackagingEngine(projects_dir)
    artifact = _load_or_build_packaging(
        project_manager,
        packaging_engine,
        project,
        topic=args.topic or project.title,
        script_excerpt=args.script_excerpt or "A curious explainer video about the selected topic.",
    )

    if args.title_index is not None:
        if not 0 <= args.title_index < len(artifact.title_options):
            raise ValueError(
                f"Title index {args.title_index} is out of range for {len(artifact.title_options)} options."
            )
        selected_title = artifact.title_options[args.title_index].title
    else:
        selected_title = args.title or artifact.selected_title

    if not selected_title or not selected_title.strip():
        raise ValueError("A selected title is required before upload.")

    artifact.selected_title = selected_title.strip()
    artifact.metadata.description = artifact.metadata.description.strip() or (
        f"{selected_title}. {artifact.metadata.description or 'A curious explainer about the selected topic.'}"
    )

    if args.create_approval:
        engine = PublishingEngine(projects_dir, provider=YouTubeProvider(
            os.environ.get("GOOGLE_CLIENT_SECRETS_FILE"),
            os.environ.get("GOOGLE_TOKEN_FILE"),
        ))
        engine.create_approval(project, approved=True, approved_by=args.approved_by)
    else:
        engine = PublishingEngine(projects_dir)

    if not os.getenv("GOOGLE_CLIENT_SECRETS_FILE") or not os.getenv("GOOGLE_TOKEN_FILE"):
        raise RuntimeError(
            "Google OAuth paths are not configured. Set GOOGLE_CLIENT_SECRETS_FILE and GOOGLE_TOKEN_FILE in .env."
        )

    live_provider = YouTubeProvider(
        os.environ["GOOGLE_CLIENT_SECRETS_FILE"],
        os.environ["GOOGLE_TOKEN_FILE"],
    )
    live_engine = PublishingEngine(projects_dir, provider=live_provider)

    if args.create_approval:
        live_engine.create_approval(project, approved=True, approved_by=args.approved_by)

    upload_metadata = packaging_engine.build_upload_metadata(
        artifact,
        category=args.category,
        language=args.language,
        made_for_kids=args.made_for_kids,
    )

    result = live_engine.publish_packaged_video(
        project=project,
        video_file=args.video_file,
        artifact=artifact,
        approved_by=args.approved_by,
        scheduled_for=args.schedule,
        category=args.category,
        language=args.language,
        made_for_kids=args.made_for_kids,
    )

    print(json.dumps({
        "project_id": project.project_id,
        "project_title": project.title,
        "title": result.title,
        "video_id": result.video_id,
        "url": result.url,
        "publish_status": result.publish_status,
        "scheduled_for": result.scheduled_for,
        "category": upload_metadata["category"],
        "language": upload_metadata["language"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
