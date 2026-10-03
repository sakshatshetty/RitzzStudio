"""Archive stale upload records after explicit confirmation of YouTube deletion."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.production_state import ProductionStateStore
from modules.project.manager import ProjectManager
from modules.publishing.engine import PublishingEngine


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read saved upload record {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"Saved upload record must contain a JSON object: {path}")
    return payload


def main() -> int:
    if os.environ.get("RITZZ_CONFIRM_DELETED_VIDEO", "").lower() != "true":
        raise ValueError(
            "Replacement upload requires the workflow confirmation that the previous "
            "YouTube video was deleted."
        )

    production_id = os.environ.get("RITZZ_PRODUCTION_ID")
    if not production_id:
        raise ValueError("RITZZ_PRODUCTION_ID is required for replacement authorization.")
    project_id = os.environ["RITZZ_PROJECT_ID"]
    run_id = os.environ["GITHUB_RUN_ID"]
    run_attempt = int(os.environ["GITHUB_RUN_ATTEMPT"])

    manager = ProjectManager(Path("projects"))
    project = manager.load_project(project_id)
    project_directory = manager.get_project_path(project)
    publishing_directory = project_directory / "publishing"
    result_file = publishing_directory / "publish.json"
    attempt_file = publishing_directory / "publish_attempt.json"
    thumbnail_file = publishing_directory / "thumbnail_upload.json"
    if not result_file.is_file():
        raise FileNotFoundError(
            f"Cannot authorize replacement; saved upload result is missing: {result_file}"
        )
    saved_result = PublishingEngine.load_publish_result(project_directory)
    if not saved_result.video_id.strip() or saved_result.publish_status != "PRIVATE":
        raise RuntimeError(
            "Replacement is allowed only for an existing private test video with a saved ID."
        )
    if not attempt_file.is_file():
        raise RuntimeError(
            "The prior upload attempt record is missing; reconcile upload history before replacement."
        )
    attempt = _load_json(attempt_file)
    if attempt.get("status") != "completed":
        raise RuntimeError(
            "The prior upload attempt is not confirmed complete; refusing replacement "
            "while its outcome may be uncertain."
        )
    if thumbnail_file.is_file():
        thumbnail = _load_json(thumbnail_file)
        if thumbnail.get("video_id") != saved_result.video_id:
            raise RuntimeError(
                "Saved thumbnail record belongs to a different video; refusing replacement."
            )

    state_store = ProductionStateStore(
        os.environ.get(
            "RITZZ_PRODUCTION_STATE_FILE",
            ".pipeline-artifacts/production_state.json",
        ),
        os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts"),
    )
    state = state_store.resume(production_id)
    state_project_id = state.get("project_id")
    if state_project_id is not None and state_project_id != project_id:
        raise RuntimeError(
            "Project ID does not match the production checkpoint; refusing replacement."
        )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_directory = (
        publishing_directory
        / "replaced_uploads"
        / f"{timestamp}_{saved_result.video_id}"
    )
    if archive_directory.exists():
        raise FileExistsError(
            f"Replacement archive already exists; refusing to overwrite it: {archive_directory}"
        )
    archive_directory.mkdir(parents=True)
    moved_files: list[tuple[Path, Path]] = []
    records = [result_file, attempt_file]
    if thumbnail_file.is_file():
        records.append(thumbnail_file)
    try:
        for source in records:
            destination = archive_directory / source.name
            shutil.move(str(source), str(destination))
            moved_files.append((destination, source))
        (archive_directory / "replacement_authorization.json").write_text(
            json.dumps(
                {
                    "previous_video_id": saved_result.video_id,
                    "previous_video_url": saved_result.url,
                    "confirmed_deleted_by": os.environ.get(
                        "GITHUB_ACTOR", "workflow_dispatch user"
                    ),
                    "confirmed_at": datetime.now(timezone.utc).isoformat(),
                    "workflow_run_id": run_id,
                    "workflow_run_attempt": run_attempt,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        state_store.authorize_deleted_video_replacement(
            run_id,
            run_attempt,
            saved_result.video_id,
        )
    except Exception:
        for archived, original in reversed(moved_files):
            if archived.exists():
                shutil.move(str(archived), str(original))
        raise

    print(
        f"Archived records for confirmed-deleted video {saved_result.video_id}; "
        "the approved private upload step may now create its replacement."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
