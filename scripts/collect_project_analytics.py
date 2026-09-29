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

from modules.analytics.collector import AnalyticsCollector, YouTubeAnalyticsProvider
from modules.project.manager import ProjectManager

load_dotenv(PROJECT_ROOT / ".env")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect YouTube analytics for a published project and persist the inventory snapshot."
    )
    parser.add_argument("--project-id", type=str, required=True, help="Existing project ID to collect analytics for.")
    parser.add_argument("--projects-dir", type=str, default=str(PROJECT_ROOT / "projects"), help="Projects directory.")
    parser.add_argument("--analytics-dir", type=str, default=str(PROJECT_ROOT / "cache" / "analytics"), help="Directory for analytics snapshots.")
    parser.add_argument("--inventory-file", type=str, default=str(PROJECT_ROOT / "cache" / "analytics" / "inventory.json"), help="Inventory JSON file path.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    projects_dir = Path(args.projects_dir)
    project_manager = ProjectManager(projects_dir)
    try:
        project = project_manager.load_project(args.project_id)
    except FileNotFoundError:
        parser.error(f"Project ID not found: {args.project_id}")

    project_path = project_manager.get_project_path(project)
    publish_file = project_path / "publishing" / "publish.json"
    if not publish_file.exists():
        raise FileNotFoundError(f"No publish artifact exists for project {args.project_id} at {publish_file}")

    credentials = os.getenv("GOOGLE_CLIENT_SECRETS_FILE") or str(PROJECT_ROOT / "secrets" / "google_Auth.json")
    token = os.getenv("GOOGLE_TOKEN_FILE") or str(PROJECT_ROOT / "secrets" / "youtube-token.json")

    provider = YouTubeAnalyticsProvider(credentials, token)
    collector = AnalyticsCollector(args.analytics_dir, provider=provider)
    snapshot = collector.collect_for_project(project, project_path, inventory_path=args.inventory_file)

    print(json.dumps({
        "project_id": project.project_id,
        "video_id": snapshot["raw"].get("video_id"),
        "views": snapshot["normalized"].get("views"),
        "like_rate": snapshot["derived"].get("like_rate"),
        "captured_at": snapshot["captured_at"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
