"""Replace selected scene images in a restored creative-package project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.project.creative_package import CreativePackageError, load_creative_package
from modules.project.manager import ProjectManager
from modules.storyboard.engine import StoryboardEngine

_SCENE_ID_PATTERN = re.compile(r"^scene_[0-9]{3,}$")
_RELEASE_TAG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def parse_scene_ids(value: str) -> list[str]:
    scene_ids = [item.strip() for item in re.split(r"[,\r\n]+", value) if item.strip()]
    if not scene_ids:
        raise ValueError("At least one scene ID is required for an image override.")
    if any(not _SCENE_ID_PATTERN.fullmatch(scene_id) for scene_id in scene_ids):
        raise ValueError(
            "Scene IDs must use scene_NNN format and be comma-separated, "
            "for example: scene_041,scene_042."
        )
    if len(scene_ids) != len(set(scene_ids)):
        raise ValueError("Image override scene IDs must not contain duplicates.")
    return scene_ids


def validate_image_override_inputs(
    *,
    mode: str,
    rerun_from_stage: str,
    release_tag: str,
    scene_ids: str,
) -> list[str]:
    if not release_tag and not scene_ids:
        return []
    if not release_tag or not scene_ids:
        raise ValueError(
            "Provide both image_override_release_tag and "
            "image_override_scene_ids, or leave both empty."
        )
    if mode != "RESUME" or rerun_from_stage != "RENDER":
        raise ValueError(
            "Image overrides are only supported with mode=RESUME and "
            "rerun_from_stage=RENDER."
        )
    if not _RELEASE_TAG_PATTERN.fullmatch(release_tag):
        raise ValueError("Image override release tag contains unsupported characters.")
    return parse_scene_ids(scene_ids)


def _read_accepted_source_file(
    project_directory: Path,
    manifest: dict[str, object],
    source_hashes: dict[str, object],
    field: str,
) -> bytes:
    relative = manifest.get(field)
    if not isinstance(relative, str) or "\\" in relative:
        raise CreativePackageError(
            f"Accepted creative package has an invalid {field}."
        )
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(":" in part for part in path.parts)
    ):
        raise CreativePackageError(
            f"Accepted creative package has an unsafe {field}."
        )
    source_path = project_directory / "creative_input"
    for part in path.parts:
        source_path /= part
    if not source_path.is_file():
        raise FileNotFoundError(f"Accepted creative file is missing: {relative}")
    contents = source_path.read_bytes()
    expected_hash = source_hashes.get(path.as_posix())
    if (
        not isinstance(expected_hash, str)
        or hashlib.sha256(contents).hexdigest() != expected_hash
    ):
        raise CreativePackageError(
            f"Accepted creative file failed its integrity check: {relative}"
        )
    return contents


def apply_creative_image_overrides(
    project_id: str,
    project_directory: str | Path,
    override_zip: str | Path,
    scene_ids: list[str],
) -> dict[str, object]:
    selected_ids = parse_scene_ids(",".join(scene_ids))
    project_path = Path(project_directory)
    acceptance_path = project_path / "creative_input" / "acceptance.json"
    if not acceptance_path.is_file():
        raise CreativePackageError(
            "Restored project is missing its accepted creative-package marker."
        )
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    accepted_manifest = acceptance.get("manifest")
    if acceptance.get("status") != "ACCEPTED" or not isinstance(
        accepted_manifest, dict
    ):
        raise CreativePackageError(
            "Restored project's original creative package is not accepted."
        )
    source_hashes = acceptance.get("source_files_sha256")
    if not isinstance(source_hashes, dict):
        raise CreativePackageError(
            "Restored project is missing accepted creative-file integrity hashes."
        )
    if accepted_manifest.get("project_id") != project_id:
        raise CreativePackageError(
            "Restored project ID does not match its accepted creative package."
        )

    original_script = _read_accepted_source_file(
        project_path,
        accepted_manifest,
        source_hashes,
        "script_file",
    ).decode("utf-8")
    package = load_creative_package(override_zip)
    if package.manifest.project_id != project_id:
        raise CreativePackageError(
            "Image override package project ID does not match the restored project."
        )
    if package.script != original_script:
        raise CreativePackageError(
            "Image override package script differs from the accepted project script."
        )

    original_storyboard_path = project_path / "storyboard" / "storyboard_source.json"
    accepted_storyboard = json.loads(
        _read_accepted_source_file(
            project_path,
            accepted_manifest,
            source_hashes,
            "storyboard_file",
        )
    )
    original_storyboard = json.loads(
        original_storyboard_path.read_text(encoding="utf-8")
    )
    if original_storyboard != accepted_storyboard:
        raise CreativePackageError(
            "Restored source storyboard differs from the accepted creative package."
        )
    original_scenes = {
        scene["scene_id"]: scene for scene in original_storyboard.get("scenes", [])
    }
    override_scenes = {
        scene.scene_id: scene for scene in package.storyboard.scenes
    }

    timed_storyboard = StoryboardEngine.load_storyboard(
        project_path / "storyboard" / "storyboard_audio_timed.json"
    )
    timed_scene_ids = {scene.scene_id for scene in timed_storyboard.scenes}
    selected_id_set = set(selected_ids)
    missing_ids = sorted(
        (selected_id_set - original_scenes.keys())
        | (selected_id_set - override_scenes.keys())
        | (selected_id_set - timed_scene_ids)
    )
    if missing_ids:
        raise CreativePackageError(
            "Image override scene IDs are not present in both the accepted "
            "storyboard and override package: " + ", ".join(missing_ids)
        )

    replacements: list[tuple[Path, bytes, str]] = []
    for scene_id in selected_ids:
        original_scene = original_scenes[scene_id]
        override_scene = override_scenes[scene_id]
        if override_scene.narration != original_scene.get("narration"):
            raise CreativePackageError(
                f"Image override scene {scene_id} changes the accepted narration."
            )
        expected_image_path = f"images/{scene_id}.png"
        if override_scene.image_file != expected_image_path:
            raise CreativePackageError(
                f"Image override scene {scene_id} must use "
                f"{expected_image_path}."
            )
        target = project_path / "images" / f"{scene_id}.png"
        if not target.is_file():
            raise FileNotFoundError(
                f"Restored scene image is missing and cannot be replaced: {target}"
            )
        image_bytes = package.source_files[override_scene.image_file]
        replacements.append(
            (target, image_bytes, hashlib.sha256(image_bytes).hexdigest())
        )

    for target, image_bytes, _digest in replacements:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.stem}.override-",
                suffix=target.suffix,
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(image_bytes)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, target)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    return {
        "project_id": project_id,
        "override_archive_sha256": package.archive_sha256,
        "replaced_scenes": [
            {"scene_id": scene_id, "image_sha256": digest}
            for scene_id, (_target, _image, digest) in zip(
                selected_ids, replacements, strict=True
            )
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True, help="Validated override package ZIP.")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--scene-ids", required=True)
    parser.add_argument(
        "--projects-dir",
        default="projects",
    )
    parser.add_argument(
        "--report",
        default=".pipeline-artifacts/image-override-result.json",
    )
    arguments = parser.parse_args()

    manager = ProjectManager(Path(arguments.projects_dir))
    project = manager.load_project(arguments.project_id)
    result = apply_creative_image_overrides(
        project.project_id,
        manager.get_project_path(project),
        arguments.zip,
        parse_scene_ids(arguments.scene_ids),
    )
    report_path = Path(arguments.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Applied image-only override to "
        f"{', '.join(item['scene_id'] for item in result['replaced_scenes'])}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
