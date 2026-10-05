"""Generate concepts and package the selected RITZZ thumbnail."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.production_state import ProductionStateStore
from modules.project.manager import ProjectManager
from modules.project.thumbnail_packaging import (
    THUMBNAIL_ARTWORK_FILENAME,
    THUMBNAIL_FILENAME,
    THUMBNAIL_IMAGE_FILENAME,
    ThumbnailPackagingEngine,
)


def _write_concept_summary(artifact: dict, output_path: Path) -> None:
    lines = [
        "# RITZZ thumbnail concept selection",
        "",
        f"**Approved topic:** {artifact['approved_topic']}",
        f"**Final title:** {artifact['selected_title']}",
        "",
        "Reply with exactly one concept number. Only trusted repository collaborators may select.",
        "",
    ]
    for index, concept in enumerate(artifact["concepts"], start=1):
        lines.extend(
            [
                f"## {index}. {concept['concept_id']} — {concept['text']}",
                "",
                f"- Visual concept: {concept['visual_concept']}",
                f"- Main subject: {concept['main_character_or_object']}",
                f"- Situation: {concept['situation']}",
                f"- Composition: {concept['composition']}",
                f"- Why it creates curiosity: {concept['curiosity_reason']}",
                f"- Relationship to title: {concept['title_relationship']}",
                "",
            ]
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _archive_project(project_directory: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz") as archive:
        archive.add(project_directory, arcname=project_directory.name)


def main() -> int:
    phase = os.environ.get("RITZZ_THUMBNAIL_PHASE", "concepts").casefold()
    project_id = os.environ["RITZZ_PROJECT_ID"]
    production_id = os.environ["RITZZ_PRODUCTION_ID"]
    artifact_root = Path(
        os.environ.get("RITZZ_PIPELINE_ARTIFACTS", ".pipeline-artifacts")
    )
    manager = ProjectManager(Path("projects"))
    project = manager.load_project(project_id)
    project_directory = manager.get_project_path(project)
    engine = ThumbnailPackagingEngine()

    if phase == "concepts":
        artifact = engine.create_concepts(
            project_directory,
            production_id=production_id,
            project_id=project_id,
        )
        artifact_root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            project_directory / THUMBNAIL_FILENAME,
            artifact_root / THUMBNAIL_FILENAME,
        )
        _write_concept_summary(artifact, artifact_root / "thumbnail_concepts.md")
        github_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if github_summary:
            with Path(github_summary).open("a", encoding="utf-8") as summary:
                summary.write(
                    (artifact_root / "thumbnail_concepts.md").read_text(
                        encoding="utf-8"
                    )
                )
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with Path(github_output).open("a", encoding="utf-8") as output:
                output.write(f"concept_count={len(artifact['concepts'])}\n")
        print(json.dumps(artifact, ensure_ascii=False, indent=2))
        return 0

    if phase != "render":
        raise ValueError(f"Unsupported thumbnail packaging phase: {phase}")
    concept_id = os.environ.get("RITZZ_THUMBNAIL_CONCEPT_ID", "").strip()
    if not concept_id:
        raise ValueError("A trusted human-selected thumbnail concept is required.")
    artifact = engine.render_selected(
        project_directory,
        production_id=production_id,
        project_id=project_id,
        concept_id=concept_id,
    )
    artifact_root.mkdir(parents=True, exist_ok=True)
    for name in (
        THUMBNAIL_FILENAME,
        THUMBNAIL_IMAGE_FILENAME,
        THUMBNAIL_ARTWORK_FILENAME,
    ):
        source = (
            project_directory / name
            if name == THUMBNAIL_FILENAME
            else project_directory / "video" / name
        )
        shutil.copy2(source, artifact_root / name)
    _archive_project(
        project_directory,
        artifact_root / "thumbnail-project.tar.gz",
    )
    state = ProductionStateStore(
        artifact_root / "production_state.json",
        artifact_root,
    ).resume(production_id)
    if state["stages"]["thumbnail_packaging"]["status"] != "running":
        raise RuntimeError("Thumbnail packaging stage is not marked running.")
    print(json.dumps(artifact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
