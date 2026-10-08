"""Build a user-metadata-preserving final video package for human review."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.project.manager import ProjectManager
from modules.project.packaging import PackagingArtifact
from modules.qa.engine import load_project_qa


def build_final_package(
    project_directory: str | Path,
    output_file: str | Path,
    *,
    human_approval: str = "PENDING",
) -> Path:
    if human_approval not in {"PENDING", "APPROVED"}:
        raise ValueError("human_approval must be PENDING or APPROVED.")
    project_path = Path(project_directory)
    acceptance_path = project_path / "creative_input" / "acceptance.json"
    if not acceptance_path.is_file():
        raise FileNotFoundError("Accepted creative package marker is missing.")
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    manifest = acceptance.get("manifest")
    if acceptance.get("status") != "ACCEPTED" or not isinstance(manifest, dict):
        raise ValueError("Creative package did not pass input acceptance.")
    source_hashes = acceptance.get("source_files_sha256")
    if not isinstance(source_hashes, dict):
        raise TypeError(
            "Accepted creative package is missing source-file integrity hashes."
        )

    def source_file(field: str) -> tuple[str, Path]:
        relative = manifest.get(field)
        if not isinstance(relative, str) or "\\" in relative:
            raise ValueError(f"Creative package has an invalid {field}.")
        path = PurePosixPath(relative)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError(f"Creative package has an unsafe {field}.")
        resolved = project_path / "creative_input"
        for part in path.parts:
            resolved /= part
        if not resolved.is_file():
            raise FileNotFoundError(f"Supplied creative file is missing: {relative}")
        expected_hash = source_hashes.get(path.as_posix())
        actual_hash = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if not isinstance(expected_hash, str) or actual_hash != expected_hash:
            raise ValueError(f"Supplied creative file integrity check failed: {relative}")
        return path.as_posix(), resolved

    supplied = {
        "script.txt": source_file("script_file"),
        "title.txt": source_file("title_file"),
        "description.txt": source_file("description_file"),
        "tags.txt": source_file("tags_file"),
        "thumbnail.png": source_file("thumbnail_file"),
    }
    packaging = PackagingArtifact.from_dict(
        json.loads((project_path / "packaging.json").read_text(encoding="utf-8"))
    )
    supplied_title = supplied["title.txt"][1].read_bytes().decode("utf-8")
    supplied_description = (
        supplied["description.txt"][1].read_bytes().decode("utf-8")
    )
    supplied_tags = supplied["tags.txt"][1].read_bytes().decode("utf-8").splitlines()
    if (
        packaging.selected_title != supplied_title
        or packaging.metadata.description != supplied_description
        or packaging.metadata.tags != supplied_tags
    ):
        raise ValueError("Packaged metadata differs from user-supplied creative files.")

    video_file = project_path / "video" / "ritzz_test.mp4"
    rendered_thumbnail = project_path / "video" / "thumbnail.png"
    if not video_file.is_file() or video_file.stat().st_size == 0:
        raise FileNotFoundError("Technically validated final video is missing.")
    if (
        not rendered_thumbnail.is_file()
        or rendered_thumbnail.read_bytes() != supplied["thumbnail.png"][1].read_bytes()
    ):
        raise ValueError("Rendered project did not preserve the supplied thumbnail.")

    qa_report = load_project_qa(project_path)
    technical_attempts = qa_report.stages.get("technical_qa", [])
    if not technical_attempts or technical_attempts[-1].status != "PASS":
        raise ValueError("Final package requires a passing technical video QA result.")
    if qa_report.status == "FAIL":
        raise ValueError("Final package cannot be created while project QA has a FAIL.")
    qa_file = project_path / "qa" / "qa_report.json"
    if not qa_file.is_file():
        raise FileNotFoundError("Final package requires the saved project QA report.")

    archive = Path(output_file)
    archive.parent.mkdir(parents=True, exist_ok=True)
    entries: dict[str, Path] = {
        "final_video.mp4": video_file,
        "thumbnail.png": supplied["thumbnail.png"][1],
        "title.txt": supplied["title.txt"][1],
        "description.txt": supplied["description.txt"][1],
        "tags.txt": supplied["tags.txt"][1],
        "script.txt": supplied["script.txt"][1],
        "qa_report.json": qa_file,
    }
    hashes = {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in entries.items()
    }
    package_manifest = {
        "workflow_version": acceptance["workflow_version"],
        "project_id": manifest["project_id"],
        "topic": manifest["topic"],
        "target_duration_minutes": manifest["target_duration_minutes"],
        "human_approval": human_approval,
        "qa_status": qa_report.status,
        "technical_qa_status": technical_attempts[-1].status,
        "files_sha256": hashes,
    }
    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as output:
        for name, source in entries.items():
            output.write(source, name)
        output.writestr(
            "package_manifest.json",
            json.dumps(package_manifest, indent=2, ensure_ascii=False) + "\n",
        )
    return archive


def main() -> int:
    project_id = os.environ["RITZZ_PROJECT_ID"]
    project = ProjectManager(Path("projects")).load_project(project_id)
    project_directory = ProjectManager(Path("projects")).get_project_path(project)
    output_file = Path(".pipeline-artifacts") / f"final-package-{project_id}.zip"
    human_approval = (
        "APPROVED"
        if os.environ.get("RITZZ_HUMAN_APPROVED", "").casefold() == "true"
        else "PENDING"
    )
    archive = build_final_package(
        project_directory,
        output_file,
        human_approval=human_approval,
    )
    print(f"Human-review package created: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
