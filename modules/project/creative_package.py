"""Validation and safe loading of user-supplied creative package ZIP files."""

from __future__ import annotations

import hashlib
import json
import re
import stat
import tempfile
import zipfile
import zlib
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.project.config import ProductionConfig
from modules.project.manager import ProjectManager
from modules.project.models import Project
from modules.project.packaging import (
    YOUTUBE_TAG_CHARACTER_LIMIT,
    PackagingArtifact,
    PackagingMetadata,
    youtube_tag_character_count,
)
from modules.script.models import Script, ScriptSection
from modules.video.image_asset_qa import inspect_image_asset

CREATIVE_PACKAGE_WORKFLOW_VERSION = "creative_flow_zip_v3"
CREATIVE_PACKAGE_MAX_ARCHIVE_BYTES = 250 * 1024 * 1024
CREATIVE_PACKAGE_MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024
CREATIVE_PACKAGE_MAX_TEXT_BYTES = 5 * 1024 * 1024
CREATIVE_PACKAGE_MAX_THUMBNAIL_BYTES = 25 * 1024 * 1024
CREATIVE_PACKAGE_MAX_IMAGE_BYTES = 25 * 1024 * 1024
CREATIVE_PACKAGE_MAX_MEMBERS = 256
_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_REQUIRED_FILE_FIELDS = (
    "script_file",
    "title_file",
    "description_file",
    "tags_file",
    "thumbnail_file",
    "storyboard_file",
)
_SCENE_ID_PATTERN = re.compile(r"^scene_[0-9]{3,}$")


class CreativePackageError(ValueError):
    """A supplied creative package is invalid or unsafe to ingest."""


class CreativePackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=80)
    topic: str = Field(min_length=1, max_length=500)
    target_duration_minutes: int = Field(ge=1, strict=True)
    script_file: str = Field(min_length=1)
    title_file: str = Field(min_length=1)
    description_file: str = Field(min_length=1)
    tags_file: str = Field(min_length=1)
    thumbnail_file: str = Field(min_length=1)
    storyboard_file: str = Field(min_length=1)
    image_files: list[str] = Field(min_length=1, max_length=200)

    @field_validator("project_id")
    @classmethod
    def validate_project_id(cls, value: str) -> str:
        if not _PROJECT_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "project_id must contain 1–80 letters, numbers, underscores, or hyphens."
            )
        return value

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("topic cannot be empty.")
        return value


class CreativeStoryboardScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scene_id: str
    narration: str = Field(min_length=1)
    visual_description: str = Field(min_length=10)
    image_prompt: str = Field(min_length=10)
    image_file: str = Field(min_length=1)

    @field_validator("scene_id")
    @classmethod
    def validate_scene_id(cls, value: str) -> str:
        if not _SCENE_ID_PATTERN.fullmatch(value):
            raise ValueError("scene_id must use the scene_NNN naming format.")
        return value


class CreativeStoryboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thumbnail_prompt: str = Field(min_length=10)
    scenes: list[CreativeStoryboardScene] = Field(min_length=1, max_length=200)


class CreativePackage(BaseModel):
    """The immutable creative files associated by a validated manifest."""

    manifest: CreativePackageManifest
    script: str
    title: str
    description: str
    tags_text: str
    tags: list[str]
    thumbnail: bytes
    storyboard: CreativeStoryboard
    archive_sha256: str
    source_files: dict[str, bytes]

    @property
    def target_duration_seconds(self) -> int:
        return self.manifest.target_duration_minutes * 60


def materialize_creative_package(
    package: CreativePackage,
    projects_directory: str | Path,
    *,
    words_per_minute: int = 140,
) -> tuple[Project, Path]:
    """Create an idempotent project from validated, immutable user files."""
    if words_per_minute < 1:
        raise ValueError("words_per_minute must be positive.")
    duration_seconds = package.target_duration_seconds
    word_count = len(package.script.split())
    estimated_seconds = word_count * 60 / words_per_minute
    minimum_duration = max(
        1,
        duration_seconds - 60,
    )
    if estimated_seconds < minimum_duration:
        raise CreativePackageError(
            "SCRIPT_DURATION_TOO_SHORT: supplied script estimates to "
            f"{estimated_seconds:.0f}s at {words_per_minute} words per minute; "
            f"target is {duration_seconds}s (minimum accepted {minimum_duration}s)."
        )
    if estimated_seconds > duration_seconds + 60:
        raise CreativePackageError(
            "SCRIPT_DURATION_TOO_LONG: supplied script estimates to "
            f"{estimated_seconds:.0f}s at {words_per_minute} words per minute; "
            f"maximum accepted is {duration_seconds + 60}s."
        )

    manager = ProjectManager(Path(projects_directory))
    project_id = package.manifest.project_id
    is_new_project = False
    try:
        project = manager.load_project(project_id)
    except FileNotFoundError:
        project = manager.create_project(
            package.manifest.topic,
            project_id=project_id,
        )
        is_new_project = True
    project_directory = manager.get_project_path(project)
    if project.title != package.manifest.topic:
        raise CreativePackageError(
            f"Project ID {project_id} already belongs to a different topic."
        )
    acceptance_path = project_directory / "creative_input" / "acceptance.json"
    acceptance_status = "IMPORTING"
    if acceptance_path.is_file():
        accepted = json.loads(acceptance_path.read_text(encoding="utf-8"))
        if accepted.get("archive_sha256") != package.archive_sha256:
            raise CreativePackageError(
                f"Project {project_id} already exists with a different creative ZIP."
            )
        source_directory = project_directory / "creative_input"
        for relative_path, contents in package.source_files.items():
            saved_path = source_directory.joinpath(
                *PurePosixPath(relative_path).parts
            )
            if saved_path.is_file() and saved_path.read_bytes() != contents:
                raise CreativePackageError(
                    "A saved user-supplied creative file was modified: "
                    f"{relative_path}"
                )
        acceptance_status = accepted.get("status", "")
        if acceptance_status == "ACCEPTED":
            for relative_path in package.source_files:
                saved_path = source_directory.joinpath(
                    *PurePosixPath(relative_path).parts
                )
                if not saved_path.is_file():
                    raise CreativePackageError(
                        "A previously accepted user-supplied creative file is missing: "
                        f"{relative_path}"
                    )
            return project, project_directory
        if acceptance_status != "IMPORTING":
            raise CreativePackageError(
                f"Project {project_id} has an invalid creative ZIP import state."
            )
    elif not is_new_project:
        raise CreativePackageError(
            f"Project {project_id} already exists and was not imported from this creative ZIP."
        )
    source_directory = project_directory / "creative_input"
    source_directory.mkdir(parents=True, exist_ok=True)
    acceptance_path.write_text(
        json.dumps(
            {
                "workflow_version": CREATIVE_PACKAGE_WORKFLOW_VERSION,
                "archive_sha256": package.archive_sha256,
                "source_files_sha256": {
                    name: hashlib.sha256(contents).hexdigest()
                    for name, contents in package.source_files.items()
                },
                "input_validation": "PASS",
                "status": "IMPORTING",
                "manifest": package.manifest.model_dump(mode="json"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for relative_path, contents in package.source_files.items():
        destination = source_directory.joinpath(*PurePosixPath(relative_path).parts)
        if destination.is_file():
            if destination.read_bytes() != contents:
                raise CreativePackageError(
                    f"A saved user-supplied creative file was modified: {relative_path}"
                )
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contents)

    first_sentence = re.split(r"(?<=[.!?])\s+", package.script.strip(), maxsplit=1)[0]
    script = Script(
        topic=package.manifest.topic,
        target_duration_seconds=duration_seconds,
        target_word_count=min(max(1, word_count), 2000),
        hook=first_sentence or package.script.strip()[:200],
        sections=[
            ScriptSection(
                section_id="supplied_script",
                section_type="explanation",
                title="Supplied narration",
                narration=package.script,
                estimated_seconds=min(180, max(10, duration_seconds)),
            )
        ],
        total_estimated_seconds=duration_seconds,
        total_word_count=word_count,
        closing_message=package.script.strip().splitlines()[-1],
        user_supplied=True,
    )
    script_directory = project_directory / "script"
    (script_directory / "script.json").write_text(
        script.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    config = ProductionConfig(
        target_duration_seconds=duration_seconds,
        minimum_duration_seconds=minimum_duration,
        words_per_minute=words_per_minute,
        scene_minimum_duration_seconds=1.0,
        scene_maximum_duration_seconds=6.0,
    )
    (project_directory / "production_config.json").write_text(
        config.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (project_directory / "topic_selection.json").write_text(
        json.dumps(
            {
                "topic": package.manifest.topic,
                "source": "creative_package",
                "target_duration_seconds": duration_seconds,
                "workflow_version": CREATIVE_PACKAGE_WORKFLOW_VERSION,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    packaging = PackagingArtifact(
        selected_title=package.title,
        metadata=PackagingMetadata(
            description=package.description,
            tags=list(package.tags),
        ),
    )
    (project_directory / "packaging.json").write_text(
        json.dumps(packaging.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    thumbnail_path = project_directory / "thumbnail" / "supplied_thumbnail.png"
    thumbnail_path.write_bytes(package.thumbnail)
    storyboard_path = project_directory / "storyboard" / "storyboard_source.json"
    storyboard_path.write_text(
        package.storyboard.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    image_directory = project_directory / "images"
    image_assets = []
    for scene in package.storyboard.scenes:
        relative_image = PurePosixPath(scene.image_file)
        image_path = image_directory / relative_image.name
        image_path.write_bytes(package.source_files[scene.image_file])
        image_assets.append(
            {
                "image_id": scene.scene_id,
                "scene_id": scene.scene_id,
                "provider": "flow_mcp",
                "prompt": scene.image_prompt,
                "file_path": str(image_path),
                "status": "completed",
                "error_message": None,
            }
        )
    (image_directory / "image_manifest.json").write_text(
        json.dumps(image_assets, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    acceptance_path.write_text(
        json.dumps(
            {
                "workflow_version": CREATIVE_PACKAGE_WORKFLOW_VERSION,
                "archive_sha256": package.archive_sha256,
                "source_files_sha256": {
                    name: hashlib.sha256(contents).hexdigest()
                    for name, contents in package.source_files.items()
                },
                "input_validation": "PASS",
                "status": "ACCEPTED",
                "manifest": package.manifest.model_dump(mode="json"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return project, project_directory


def load_creative_package(archive_path: str | Path) -> CreativePackage:
    """Validate a ZIP package before any paid or external production calls."""
    path = Path(archive_path)
    if not path.is_file():
        raise CreativePackageError(f"Creative package ZIP does not exist: {path}")
    if path.stat().st_size > CREATIVE_PACKAGE_MAX_ARCHIVE_BYTES:
        raise CreativePackageError("Creative package ZIP exceeds the 250 MiB limit.")

    digest = hashlib.sha256()
    with path.open("rb") as archive_file:
        for block in iter(lambda: archive_file.read(1024 * 1024), b""):
            digest.update(block)
    archive_digest = digest.hexdigest()
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            names = [item.filename for item in members]
            _validate_zip_members(members)
            if len(names) != len(set(names)):
                raise CreativePackageError("ZIP contains duplicate file paths.")
            if "project.json" not in names:
                raise CreativePackageError("INPUT_VALIDATION_FAILED: project.json is missing.")

            manifest_bytes = _read_member(
                archive, "project.json", max_bytes=CREATIVE_PACKAGE_MAX_TEXT_BYTES
            )
            try:
                manifest_payload = json.loads(
                    manifest_bytes,
                    object_pairs_hook=_unique_json_object,
                )
                manifest = CreativePackageManifest.model_validate(manifest_payload)
            except (ValueError, TypeError) as exc:
                raise CreativePackageError(
                    f"INPUT_VALIDATION_FAILED: project.json is invalid: {exc}"
                ) from exc

            referenced = {
                field: _validate_manifest_path(getattr(manifest, field), field)
                for field in _REQUIRED_FILE_FIELDS
            }
            image_files = [
                _validate_manifest_path(name, "image_files")
                for name in manifest.image_files
            ]
            if len(image_files) != len(set(image_files)):
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: image_files references must be distinct."
                )
            if len(set(referenced.values())) != len(referenced):
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: manifest file references must be distinct."
                )
            all_referenced = {*referenced.values(), *image_files}
            if "project.json" in all_referenced:
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: asset files cannot reference project.json."
                )
            if len(all_referenced) != len(referenced) + len(image_files):
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: manifest file references must be distinct."
                )
            expected_files = {"project.json", *all_referenced}
            expected_directories = {
                "/".join(PurePosixPath(name).parts[:index]) + "/"
                for name in expected_files
                for index in range(1, len(PurePosixPath(name).parts))
            }
            unexpected_directories = {
                item.filename for item in members if item.is_dir()
            } - expected_directories
            if unexpected_directories:
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: ZIP contains unexpected directories: "
                    + ", ".join(sorted(unexpected_directories))
                )
            regular_files = {
                item.filename for item in members if not item.is_dir()
            }
            if regular_files != expected_files:
                unexpected = sorted(regular_files - expected_files)
                missing = sorted(expected_files - regular_files)
                details = []
                if missing:
                    details.append("missing: " + ", ".join(missing))
                if unexpected:
                    details.append("unexpected: " + ", ".join(unexpected))
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: ZIP file list does not match the manifest"
                    + (": " + "; ".join(details) if details else ".")
                )

            source_files = {
                name: _read_member(
                    archive,
                    name,
                    max_bytes=(
                        CREATIVE_PACKAGE_MAX_THUMBNAIL_BYTES
                        if name == referenced["thumbnail_file"]
                        else CREATIVE_PACKAGE_MAX_IMAGE_BYTES
                        if name in image_files
                        else CREATIVE_PACKAGE_MAX_TEXT_BYTES
                    ),
                )
                for name in expected_files
            }
            script = _read_text_member(archive, referenced["script_file"], "script")
            title = _read_text_member(archive, referenced["title_file"], "title")
            description = _read_text_member(
                archive, referenced["description_file"], "description"
            )
            tags_text = _read_text_member(archive, referenced["tags_file"], "tags")
            tags = _parse_tags(tags_text)
            if len(title.strip()) > 100:
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: title must be at most 100 characters."
                )
            if len(description) > 5000:
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: description must be at most 5000 characters."
                )
            if youtube_tag_character_count(tags) > YOUTUBE_TAG_CHARACTER_LIMIT:
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: tags exceed YouTube's 500-character "
                    "limit after accounting for commas and quotes around multi-word tags."
                )
            thumbnail = _read_member(
                archive,
                referenced["thumbnail_file"],
                max_bytes=CREATIVE_PACKAGE_MAX_THUMBNAIL_BYTES,
            )
            _validate_thumbnail(thumbnail, referenced["thumbnail_file"])
            try:
                storyboard = CreativeStoryboard.model_validate_json(
                    source_files[referenced["storyboard_file"]]
                )
            except (ValueError, TypeError) as exc:
                raise CreativePackageError(
                    f"INPUT_VALIDATION_FAILED: storyboard JSON is invalid: {exc}"
                ) from exc
            if len(storyboard.scenes) != len(image_files):
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: storyboard scene count does not match "
                    "the image file count."
                )
            scene_image_files = [scene.image_file for scene in storyboard.scenes]
            if scene_image_files != image_files:
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: storyboard image_file values must match "
                    "project.json image_files in scene order."
                )
            scene_ids = [scene.scene_id for scene in storyboard.scenes]
            if len(scene_ids) != len(set(scene_ids)):
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: storyboard scene IDs must be unique."
                )
            for scene in storyboard.scenes:
                image_path = PurePosixPath(scene.image_file)
                if (
                    image_path.parts[0] != "images"
                    or image_path.name != f"{scene.scene_id}.png"
                ):
                    raise CreativePackageError(
                        "INPUT_VALIDATION_FAILED: each scene image must be named "
                        f"images/{scene.scene_id}.png."
                    )
            script_compact = _compact_text(script)
            storyboard_compact = "".join(
                _compact_text(scene.narration) for scene in storyboard.scenes
            )
            if storyboard_compact != script_compact:
                raise CreativePackageError(
                    "INPUT_VALIDATION_FAILED: storyboard narration excerpts must "
                    "cover the supplied script exactly once and in order."
                )
            for scene in storyboard.scenes:
                image_data = source_files[scene.image_file]
                _validate_scene_image(image_data, scene.image_file)
    except CreativePackageError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError, zlib.error) as exc:
        raise CreativePackageError(
            f"INPUT_VALIDATION_FAILED: ZIP could not be read: {exc}"
        ) from exc

    return CreativePackage(
        manifest=manifest,
        script=script,
        title=title,
        description=description,
        tags_text=tags_text,
        tags=tags,
        thumbnail=thumbnail,
        storyboard=storyboard,
        archive_sha256=archive_digest,
        source_files=source_files,
    )


def _compact_text(value: str) -> str:
    return "".join(character.lower() for character in value if character.isalnum())


def _validate_zip_members(members: list[zipfile.ZipInfo]) -> None:
    if len(members) > CREATIVE_PACKAGE_MAX_MEMBERS:
        raise CreativePackageError(
            f"Creative package ZIP may contain at most {CREATIVE_PACKAGE_MAX_MEMBERS} entries."
        )
    expanded_size = 0
    seen_casefolded: set[str] = set()
    for item in members:
        name = item.filename
        if not name or "\x00" in name or "\\" in name:
            raise CreativePackageError("ZIP contains an invalid or unsafe path.")
        normalized = PurePosixPath(name)
        if normalized.is_absolute() or any(
            part in {"", ".", ".."} for part in normalized.parts
        ) or any(":" in part for part in normalized.parts):
            raise CreativePackageError(f"ZIP contains an unsafe path: {name}")
        folded = name.casefold()
        if folded in seen_casefolded:
            raise CreativePackageError(
                f"ZIP contains paths that collide on Windows: {name}"
            )
        seen_casefolded.add(folded)
        mode = item.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise CreativePackageError(f"ZIP may not contain symlinks: {name}")
        if item.flag_bits & 0x1:
            raise CreativePackageError(f"Encrypted ZIP members are not supported: {name}")
        expanded_size += item.file_size
        if expanded_size > CREATIVE_PACKAGE_MAX_UNCOMPRESSED_BYTES:
            raise CreativePackageError(
                "Creative package expands beyond the 300 MiB limit."
            )
        if item.file_size and (
            item.compress_size == 0 or item.file_size > item.compress_size * 1000
        ):
            raise CreativePackageError(
                f"ZIP member has an unsafe compression ratio: {name}"
            )


def _validate_manifest_path(value: str, field: str) -> str:
    if "\\" in value or "\x00" in value:
        raise CreativePackageError(f"{field} must be a safe relative POSIX path.")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(":" in part for part in path.parts)
    ):
        raise CreativePackageError(f"{field} must be a safe relative POSIX path.")
    return path.as_posix()


def _read_member(
    archive: zipfile.ZipFile,
    name: str,
    *,
    max_bytes: int,
) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > max_bytes:
        raise CreativePackageError(f"ZIP member exceeds its size limit: {name}")
    data = archive.read(info)
    if len(data) != info.file_size:
        raise CreativePackageError(f"ZIP member was truncated: {name}")
    return data


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CreativePackageError(
                f"INPUT_VALIDATION_FAILED: project.json repeats field {key!r}."
            )
        result[key] = value
    return result


def _read_text_member(
    archive: zipfile.ZipFile,
    name: str,
    label: str,
) -> str:
    try:
        text = _read_member(
            archive, name, max_bytes=CREATIVE_PACKAGE_MAX_TEXT_BYTES
        ).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CreativePackageError(
            f"INPUT_VALIDATION_FAILED: {label} must be UTF-8 text."
        ) from exc
    if not text.strip() or "\x00" in text:
        raise CreativePackageError(
            f"INPUT_VALIDATION_FAILED: {label} is empty or contains binary data."
        )
    return text


def _parse_tags(tags_text: str) -> list[str]:
    tags = tags_text.splitlines()
    if not tags or any(not tag or tag != tag.strip() for tag in tags):
        raise CreativePackageError(
            "INPUT_VALIDATION_FAILED: tags.txt must contain one non-empty, "
            "trimmed tag per line."
        )
    if any(len(tag) > 500 for tag in tags):
        raise CreativePackageError("INPUT_VALIDATION_FAILED: a tag exceeds 500 characters.")
    return tags


def _validate_thumbnail(data: bytes, filename: str) -> None:
    if Path(filename).suffix.casefold() != ".png":
        raise CreativePackageError(
            "INPUT_VALIDATION_FAILED: thumbnail_file must reference a PNG image."
        )
    with tempfile.TemporaryDirectory(prefix="ritzz_creative_thumbnail_") as directory:
        thumbnail_path = Path(directory) / "thumbnail.png"
        thumbnail_path.write_bytes(data)
        try:
            inspection = inspect_image_asset(thumbnail_path)
        except (OSError, ValueError) as exc:
            raise CreativePackageError(
                f"INPUT_VALIDATION_FAILED: thumbnail.png is not a readable RGB/RGBA PNG: {exc}"
            ) from exc
    if (
        inspection.width < 1280
        or inspection.height < 720
        or abs(inspection.width * 9 - inspection.height * 16) > 16
    ):
        raise CreativePackageError(
            "INPUT_VALIDATION_FAILED: thumbnail must be 16:9 (allowing one-pixel "
            "rounding) and at least 1280x720."
        )


def _validate_scene_image(data: bytes, filename: str) -> None:
    if Path(filename).suffix.casefold() != ".png":
        raise CreativePackageError(
            f"INPUT_VALIDATION_FAILED: scene image must be a PNG: {filename}"
        )
    with tempfile.TemporaryDirectory(prefix="ritzz_creative_scene_") as directory:
        image_path = Path(directory) / "scene.png"
        image_path.write_bytes(data)
        try:
            inspection = inspect_image_asset(image_path)
        except (OSError, ValueError) as exc:
            raise CreativePackageError(
                f"INPUT_VALIDATION_FAILED: scene image is not a readable RGB/RGBA PNG "
                f"({filename}): {exc}"
            ) from exc
    if inspection.width != 1536 or inspection.height != 864:
        raise CreativePackageError(
            "INPUT_VALIDATION_FAILED: scene images must be exactly 1536x864; "
            f"{filename} is {inspection.width}x{inspection.height}."
        )
