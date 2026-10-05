"""Package final YouTube metadata from a rendered and QA-checked project."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.production_state import ProductionStateStore
from modules.project.manager import ProjectManager
from modules.project.metadata_packaging import (
    METADATA_FILENAME,
    METADATA_VERSION,
    MetadataPackagingEngine,
)
from modules.video.render_engine import FFmpegVideoRenderer


def _write_github_summary(metadata: dict, summary_file: str | None) -> None:
    if not summary_file:
        return
    repository = os.environ.get("GITHUB_REPOSITORY")
    review_run_id = os.environ.get("RITZZ_REVIEW_RUN_ID")
    review_link = (
        f"https://github.com/{repository}/actions/runs/{review_run_id}"
        if repository and review_run_id
        else None
    )
    lines = [
        "# Final YouTube metadata",
        "",
        f"**Status:** {metadata['status']}",
        f"**Selected title:** {metadata['selected_title']}",
        "",
        "## Title options",
    ]
    lines.extend(
        f"- **{option['title']}** — {option.get('rationale', '')}"
        for option in metadata["title_options"]
    )
    if metadata.get("title_lint"):
        lines.extend(
            [
                "",
                "## Title length checks",
                "",
            ]
        )
        lines.extend(
            (
                f"- {item['characters']} characters — "
                f"{'mobile preview may truncate' if item['mobile_truncation_risk'] else 'within 40-character mobile preview'}; "
                f"{'desktop preview may truncate' if item['desktop_truncation_risk'] else 'within 60-character desktop preview'}"
            )
            for item in metadata["title_lint"]
        )
    lines.extend(
        [
            "",
            "## Description",
            "",
            metadata["description"],
            "",
            "## Tags",
            "",
            ", ".join(metadata["tags"]),
            "",
            "## QA",
            "",
            f"- Technical video QA: {metadata['qa_status']['technical_qa']}",
            f"- Rendered semantic QA: {metadata['qa_status']['rendered_semantic_qa']}",
            "",
            (
                f"[Open rendered video and artifacts]({review_link})"
                if review_link
                else "Review the rendered video artifact before final approval."
            ),
            "No upload is performed by metadata packaging.",
        ]
    )
    with Path(summary_file).open("a", encoding="utf-8") as summary:
        summary.write("\n".join(lines) + "\n")


def _archive_project(project_directory: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz") as archive:
        archive.add(project_directory, arcname=project_directory.name)


def main() -> int:
    production_id = os.environ["RITZZ_PRODUCTION_ID"]
    project_id = os.environ["RITZZ_PROJECT_ID"]
    artifacts_directory = Path(
        os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts")
    )
    state_file = artifacts_directory / "production_state.json"
    store = ProductionStateStore(state_file, artifacts_directory)
    state = store.resume(production_id)
    if state.get("project_id") != project_id:
        raise RuntimeError("Production checkpoint project ID does not match.")
    if state["stages"]["render_video"]["status"] != "completed":
        raise RuntimeError("Video rendering must be complete before metadata packaging.")

    project_manager = ProjectManager(Path("projects"))
    project = project_manager.load_project(project_id)
    project_directory = project_manager.get_project_path(project)
    metadata_file = project_directory / METADATA_FILENAME
    stage_state = state["stages"]["metadata_packaging"]
    if stage_state["status"] == "completed":
        if not metadata_file.is_file():
            raise FileNotFoundError(
                f"Completed metadata artifact is missing: {metadata_file}"
            )
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        if (
            metadata.get("status") != "COMPLETE"
            or metadata.get("production_id") != production_id
            or metadata.get("project_id") != project_id
        ):
            raise RuntimeError("Completed metadata stage has an invalid metadata artifact.")
        artifact_copy = artifacts_directory / METADATA_FILENAME
        if not artifact_copy.is_file():
            shutil.copy2(metadata_file, artifact_copy)
        _write_github_summary(metadata, os.environ.get("GITHUB_STEP_SUMMARY"))
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
        return 0

    store.start_stage("metadata_packaging")
    try:
        video_file = project_directory / "video" / "ritzz_test.mp4"
        render_metadata = FFmpegVideoRenderer()._probe_media(video_file)
        metadata = MetadataPackagingEngine().package(
            project_directory,
            production_id=production_id,
            project_id=project_id,
            render_metadata=render_metadata,
            force_regenerate=(
                os.environ.get("RITZZ_RERUN_METADATA", "").casefold() == "true"
            ),
        )
        if not project.steps.get("packaging"):
            project_manager.complete_step(project_id, "packaging")
        artifacts_directory.mkdir(parents=True, exist_ok=True)
        artifact_copy = artifacts_directory / METADATA_FILENAME
        shutil.copy2(metadata_file, artifact_copy)
        project_archive = artifacts_directory / "metadata-project.tar.gz"
        _archive_project(project_directory, project_archive)
        store.complete_stage(
            "metadata_packaging",
            [METADATA_FILENAME, "metadata-project.tar.gz"],
            project_id=project_id,
        )
    except Exception as exc:
        try:
            artifacts_directory.mkdir(parents=True, exist_ok=True)
            if metadata_file.is_file():
                try:
                    failed_metadata = json.loads(
                        metadata_file.read_text(encoding="utf-8")
                    )
                except json.JSONDecodeError:
                    failed_metadata = {}
                if not isinstance(failed_metadata, dict):
                    failed_metadata = {}
                failed_metadata.update(
                    {
                        "metadata_version": METADATA_VERSION,
                        "production_id": production_id,
                        "project_id": project_id,
                        "status": "FAILED",
                        "error": str(exc),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                metadata_file.write_text(
                    json.dumps(failed_metadata, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                shutil.copy2(metadata_file, artifacts_directory / METADATA_FILENAME)
            project_archive = artifacts_directory / "metadata-project.tar.gz"
            _archive_project(project_directory, project_archive)
        finally:
            store.fail_stage(
                "metadata_packaging",
                str(exc),
                [
                    path
                    for path in (METADATA_FILENAME, "metadata-project.tar.gz")
                    if (artifacts_directory / path).is_file()
                ],
                project_id=project_id,
            )
        raise

    _write_github_summary(metadata, os.environ.get("GITHUB_STEP_SUMMARY"))
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
