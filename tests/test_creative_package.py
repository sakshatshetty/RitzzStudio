import json
import struct
import zlib
from pathlib import Path
from zipfile import ZipFile

import pytest

from modules.image.batch import ImageBatchEngine
from modules.project.creative_package import (
    CreativePackageError,
    load_creative_package,
    materialize_creative_package,
)
from modules.qa.engine import record_stage_qa
from modules.qa.models import QAStageResult
from scripts.package_creative_production import build_final_package


def _png(width: int = 1280, height: int = 720) -> bytes:
    row = b"\x00" + b"\x18\x76\xaa" * width
    raw = row * height

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _write_package(
    path: Path,
    *,
    project_id: str = "20261007_001",
    script: str | None = None,
    overrides: dict | None = None,
    extra_files: dict[str, bytes] | None = None,
    thumbnail_size: tuple[int, int] = (1280, 720),
) -> dict[str, bytes]:
    supplied_script = script or " ".join(["This is a supplied narration sentence."] * 24)
    manifest = {
        "project_id": project_id,
        "topic": "A user-selected curiosity topic",
        "target_duration_minutes": 1,
        "script_file": "script.txt",
        "title_file": "title.txt",
        "description_file": "description.txt",
        "tags_file": "tags.txt",
        "thumbnail_file": "thumbnail.png",
        "storyboard_file": "storyboard.json",
        "image_files": ["images/scene_001.png"],
    }
    manifest.update(overrides or {})
    files = {
        "project.json": json.dumps(manifest).encode(),
        manifest["script_file"]: supplied_script.encode(),
        manifest["title_file"]: b"Supplied title exactly",
        manifest["description_file"]: b"Supplied description exactly.\nLine two.",
        manifest["tags_file"]: b"tag one\ntag two\n",
        manifest["thumbnail_file"]: _png(*thumbnail_size),
        manifest["storyboard_file"]: json.dumps(
            {
                "thumbnail_prompt": "A clean Flow thumbnail prompt with no text.",
                "scenes": [
                    {
                        "scene_id": "scene_001",
                        "narration": supplied_script,
                        "visual_description": "A supplied visual description.",
                        "image_prompt": "A supplied Flow image-generation prompt.",
                        "image_file": "images/scene_001.png",
                    }
                ]
            }
        ).encode(),
        "images/scene_001.png": _png(1536, 864),
    }
    files.update(extra_files or {})
    with ZipFile(path, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    return files


def test_loads_manifest_associated_files_and_preserves_exact_values(tmp_path):
    archive = tmp_path / "creative.zip"
    files = _write_package(archive)

    package = load_creative_package(archive)

    assert package.manifest.project_id == "20261007_001"
    assert package.manifest.topic == "A user-selected curiosity topic"
    assert package.script == files["script.txt"].decode()
    assert package.title == "Supplied title exactly"
    assert package.description == "Supplied description exactly.\nLine two."
    assert package.tags == ["tag one", "tag two"]
    assert package.thumbnail == files["thumbnail.png"]
    assert package.storyboard.scenes[0].scene_id == "scene_001"


def test_rejects_missing_required_member_before_ingestion(tmp_path):
    archive = tmp_path / "missing.zip"
    files = _write_package(archive)
    del files["thumbnail.png"]
    with ZipFile(archive, "w") as output:
        for name, contents in files.items():
            output.writestr(name, contents)

    with pytest.raises(CreativePackageError, match="missing: thumbnail.png"):
        load_creative_package(archive)


def test_rejects_storyboard_not_covering_the_script_in_order(tmp_path):
    archive = tmp_path / "storyboard-mismatch.zip"
    files = _write_package(archive)
    storyboard = json.loads(files["storyboard.json"])
    storyboard["scenes"][0]["narration"] = "A different script excerpt."
    files["storyboard.json"] = json.dumps(storyboard).encode()
    with ZipFile(archive, "w") as output:
        for name, contents in files.items():
            output.writestr(name, contents)

    with pytest.raises(CreativePackageError, match="cover the supplied script"):
        load_creative_package(archive)


def test_rejects_scene_images_with_incorrect_resolution(tmp_path):
    archive = tmp_path / "invalid-scene-image.zip"
    files = _write_package(
        archive,
        extra_files={"images/scene_001.png": _png(1280, 720)},
    )
    with ZipFile(archive, "w") as output:
        for name, contents in files.items():
            output.writestr(name, contents)

    with pytest.raises(CreativePackageError, match="exactly 1536x864"):
        load_creative_package(archive)


@pytest.mark.parametrize(
    ("thumbnail_size", "accepted"),
    [
        ((1672, 941), True),
        ((1672, 945), False),
    ],
)
def test_thumbnail_allows_one_pixel_rounding_but_rejects_other_ratios(
    tmp_path,
    thumbnail_size,
    accepted,
):
    archive = tmp_path / "thumbnail-ratio.zip"
    _write_package(archive, thumbnail_size=thumbnail_size)

    if accepted:
        package = load_creative_package(archive)
        assert package.manifest.thumbnail_file == "thumbnail.png"
    else:
        with pytest.raises(CreativePackageError, match="one-pixel rounding"):
            load_creative_package(archive)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("script_file", "../script.txt", "unsafe path"),
        ("project_id", "../unsafe", "project_id"),
    ],
)
def test_rejects_unsafe_manifest_paths_and_ids(tmp_path, field, value, message):
    archive = tmp_path / "unsafe.zip"
    _write_package(archive, overrides={field: value})

    with pytest.raises(CreativePackageError, match=message):
        load_creative_package(archive)


def test_rejects_unreferenced_files_and_invalid_thumbnail(tmp_path):
    archive = tmp_path / "extra.zip"
    _write_package(archive, extra_files={"notes.txt": b"not in manifest"})

    with pytest.raises(CreativePackageError, match="unexpected: notes.txt"):
        load_creative_package(archive)

    invalid_thumbnail = tmp_path / "invalid-thumbnail.zip"
    _write_package(
        invalid_thumbnail,
        extra_files={"unused.txt": b""},
    )
    files = _write_package(invalid_thumbnail)
    files["thumbnail.png"] = b"not an image"
    with ZipFile(invalid_thumbnail, "w") as output:
        for name, contents in files.items():
            output.writestr(name, contents)

    with pytest.raises(CreativePackageError, match="thumbnail.png"):
        load_creative_package(invalid_thumbnail)


def test_rejects_duplicate_manifest_keys_and_platform_metadata_overflow(tmp_path):
    duplicate_archive = tmp_path / "duplicate-manifest-field.zip"
    files = _write_package(duplicate_archive)
    manifest = json.loads(files["project.json"])
    duplicate_manifest = (
        json.dumps(manifest)[:-1] + ',"topic":"shadow topic"}'
    ).encode()
    files["project.json"] = duplicate_manifest
    with ZipFile(duplicate_archive, "w") as output:
        for name, contents in files.items():
            output.writestr(name, contents)

    with pytest.raises(CreativePackageError, match="repeats field 'topic'"):
        load_creative_package(duplicate_archive)

    title_archive = tmp_path / "long-title.zip"
    _write_package(title_archive)
    with ZipFile(title_archive) as original:
        files = {item.filename: original.read(item) for item in original.infolist()}
    files["title.txt"] = b"x" * 101
    with ZipFile(title_archive, "w") as output:
        for name, contents in files.items():
            output.writestr(name, contents)

    with pytest.raises(CreativePackageError, match="100 characters"):
        load_creative_package(title_archive)


def test_rejects_tags_over_encoded_youtube_limit_even_when_raw_text_fits(tmp_path):
    archive = tmp_path / "encoded-tag-limit.zip"
    tags = [("x" * 20) + " " + "y" for _ in range(20)] + ["z"]
    assert sum(map(len, tags)) < 500
    _write_package(
        archive,
        extra_files={"tags.txt": "\n".join(tags).encode()},
    )

    with pytest.raises(
        CreativePackageError,
        match="commas and quotes around multi-word tags",
    ):
        load_creative_package(archive)


def test_materializes_immutable_creative_assets_for_existing_engines(tmp_path):
    archive = tmp_path / "creative.zip"
    files = _write_package(archive)
    package = load_creative_package(archive)

    project, project_directory = materialize_creative_package(
        package,
        tmp_path / "projects",
    )

    assert project.project_id == package.manifest.project_id
    assert (
        project_directory / "creative_input" / "script.txt"
    ).read_bytes() == files["script.txt"]
    assert (
        project_directory / "thumbnail" / "supplied_thumbnail.png"
    ).read_bytes() == files["thumbnail.png"]
    script = json.loads(
        (project_directory / "script" / "script.json").read_text(encoding="utf-8")
    )
    assert script["user_supplied"] is True
    assert script["sections"][0]["narration"] == files["script.txt"].decode()
    packaging = json.loads(
        (project_directory / "packaging.json").read_text(encoding="utf-8")
    )
    assert packaging["selected_title"] == "Supplied title exactly"
    assert packaging["metadata"]["description"] == (
        "Supplied description exactly.\nLine two."
    )
    assert packaging["metadata"]["tags"] == ["tag one", "tag two"]
    acceptance = json.loads(
        (project_directory / "creative_input" / "acceptance.json").read_text(
            encoding="utf-8"
        )
    )
    assert acceptance["status"] == "ACCEPTED"
    assert acceptance["manifest"]["thumbnail_file"] == "thumbnail.png"
    assert (
        project_directory / "storyboard" / "storyboard_source.json"
    ).is_file()
    assert (
        project_directory / "images" / "scene_001.png"
    ).read_bytes() == files["images/scene_001.png"]
    image_manifest = json.loads(
        (project_directory / "images" / "image_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert image_manifest[0]["provider"] == "flow_mcp"
    assert image_manifest[0]["scene_id"] == "scene_001"
    loaded_assets = ImageBatchEngine.load_manifest(
        project_directory / "images" / "image_manifest.json"
    )
    assert len(loaded_assets) == 1
    assert loaded_assets[0].provider == "flow_mcp"

    resumed_project, resumed_directory = materialize_creative_package(
        package,
        tmp_path / "projects",
    )
    assert resumed_project.project_id == project.project_id
    assert resumed_directory == project_directory


def test_rejects_too_short_script_before_creating_project(tmp_path):
    archive = tmp_path / "short-script.zip"
    _write_package(
        archive,
        script="Only a few words.",
        overrides={"target_duration_minutes": 8},
    )
    package = load_creative_package(archive)

    with pytest.raises(CreativePackageError, match="SCRIPT_DURATION_TOO_SHORT"):
        materialize_creative_package(package, tmp_path / "projects")

    assert not (tmp_path / "projects").exists()


def test_rejects_project_id_reuse_with_different_zip(tmp_path):
    projects = tmp_path / "projects"
    first_archive = tmp_path / "first.zip"
    _write_package(first_archive)
    first = load_creative_package(first_archive)
    materialize_creative_package(first, projects)

    second_archive = tmp_path / "second.zip"
    _write_package(second_archive, script=" ".join(["Different supplied narration."] * 24))
    second = load_creative_package(second_archive)
    with pytest.raises(CreativePackageError, match="different creative ZIP"):
        materialize_creative_package(second, projects)


def test_rejects_project_id_reuse_for_a_different_topic(tmp_path):
    projects = tmp_path / "projects"
    original_archive = tmp_path / "original-topic.zip"
    _write_package(original_archive)
    original = load_creative_package(original_archive)
    materialize_creative_package(original, projects)

    different_topic_archive = tmp_path / "different-topic.zip"
    _write_package(
        different_topic_archive,
        overrides={"topic": "A different user-selected topic"},
    )
    different_topic = load_creative_package(different_topic_archive)

    with pytest.raises(CreativePackageError, match="different topic"):
        materialize_creative_package(different_topic, projects)


def test_final_package_keeps_user_metadata_and_thumbnail_exact(tmp_path):
    archive = tmp_path / "creative.zip"
    source_files = _write_package(
        archive,
        extra_files={
            "title.txt": b"Supplied title exactly\r\n",
            "description.txt": (
                b"Supplied description exactly.\r\nLine two.\r\n"
            ),
            "tags.txt": b"tag one\r\ntag two\r\n",
        },
    )
    package = load_creative_package(archive)
    _, project_directory = materialize_creative_package(
        package,
        tmp_path / "projects",
    )
    video_directory = project_directory / "video"
    (video_directory / "ritzz_test.mp4").write_bytes(b"finished video")
    (video_directory / "thumbnail.png").write_bytes(source_files["thumbnail.png"])
    record_stage_qa(
        project_directory,
        QAStageResult(stage="technical_qa", status="PASS"),
    )
    record_stage_qa(
        project_directory,
        QAStageResult(stage="image_semantic_qa", status="REVIEW"),
    )
    output = build_final_package(
        project_directory,
        tmp_path / "final-package.zip",
    )

    with ZipFile(output) as final_package:
        assert final_package.read("title.txt") == source_files["title.txt"]
        assert final_package.read("description.txt") == source_files["description.txt"]
        assert final_package.read("tags.txt") == source_files["tags.txt"]
        assert final_package.read("thumbnail.png") == source_files["thumbnail.png"]
        manifest = json.loads(final_package.read("package_manifest.json"))
        assert manifest["human_approval"] == "PENDING"
        assert manifest["qa_status"] == "REVIEW"
        assert manifest["technical_qa_status"] == "PASS"

    approved_output = build_final_package(
        project_directory,
        tmp_path / "approved-package.zip",
        human_approval="APPROVED",
    )
    with ZipFile(approved_output) as final_package:
        manifest = json.loads(final_package.read("package_manifest.json"))
        assert manifest["human_approval"] == "APPROVED"
