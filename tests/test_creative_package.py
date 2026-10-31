import hashlib
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
from modules.storyboard.models import Storyboard, StoryboardScene
from scripts.apply_creative_image_overrides import (
    apply_creative_image_overrides,
    parse_scene_ids,
    validate_image_override_inputs,
)
from scripts.package_creative_production import build_final_package


def _png(
    width: int = 1280,
    height: int = 720,
    color: tuple[int, int, int] = (24, 118, 170),
) -> bytes:
    row = b"\x00" + bytes(color) * width
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
    max_words_per_scene: int = 14,
    overrides: dict | None = None,
    extra_files: dict[str, bytes] | None = None,
    thumbnail_size: tuple[int, int] = (1280, 720),
) -> dict[str, bytes]:
    default_sentence = (
        "Supplied narration uses clear complete sentences with timed spoken lines "
        "for each visual scene."
    )
    supplied_script = script or " ".join([default_sentence] * 30)
    script_words = supplied_script.split()
    narration_chunks = [
        " ".join(script_words[start : start + max_words_per_scene])
        for start in range(0, len(script_words), max_words_per_scene)
    ]
    scenes = [
        {
            "scene_id": f"scene_{index:03}",
            "narration": narration,
            "visual_description": "A supplied visual description.",
            "image_prompt": "A supplied Flow image-generation prompt.",
            "image_file": f"images/scene_{index:03}.png",
        }
        for index, narration in enumerate(narration_chunks, start=1)
    ]
    image_files = [scene["image_file"] for scene in scenes]
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
        "image_files": image_files,
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
                "scenes": scenes,
            }
        ).encode(),
    }
    files.update({image_file: _png(1536, 864) for image_file in image_files})
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


def _materialize_project_with_timed_storyboard(tmp_path):
    archive = tmp_path / "original.zip"
    files = _write_package(archive)
    package = load_creative_package(archive)
    project, project_directory = materialize_creative_package(
        package,
        tmp_path / "projects",
    )
    timed_storyboard = Storyboard(
        topic=package.manifest.topic,
        target_duration_seconds=60,
        scenes=[
            StoryboardScene(
                scene_id=scene.scene_id,
                section_id="supplied_script",
                start_seconds=index * 2.0,
                duration_seconds=2.0,
                narration=scene.narration,
                visual_description=scene.visual_description,
                image_prompt=scene.image_prompt,
            )
            for index, scene in enumerate(package.storyboard.scenes)
        ],
        total_scene_duration_seconds=2.0 * len(package.storyboard.scenes),
    )
    (project_directory / "storyboard" / "storyboard_audio_timed.json").write_text(
        timed_storyboard.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return project, project_directory, files, package


def _write_override_package(path, original_files, replacements):
    files = dict(original_files)
    files.update(replacements)
    with ZipFile(path, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    return path


def test_image_override_replaces_multiple_images_without_changing_storyboard(
    tmp_path,
):
    project, project_directory, original_files, package = (
        _materialize_project_with_timed_storyboard(tmp_path)
    )
    original_timed_storyboard = (
        project_directory / "storyboard" / "storyboard_audio_timed.json"
    ).read_bytes()
    original_source_storyboard = (
        project_directory / "storyboard" / "storyboard_source.json"
    ).read_bytes()
    replacement_images = {
        "images/scene_001.png": _png(1536, 864, color=(200, 30, 40)),
        "images/scene_002.png": _png(1536, 864, color=(30, 180, 60)),
    }
    override_zip = _write_override_package(
        tmp_path / "override.zip",
        original_files,
        replacement_images,
    )

    result = apply_creative_image_overrides(
        project.project_id,
        project_directory,
        override_zip,
        ["scene_001", "scene_002"],
    )

    assert [item["scene_id"] for item in result["replaced_scenes"]] == [
        "scene_001",
        "scene_002",
    ]
    assert (
        project_directory / "images" / "scene_001.png"
    ).read_bytes() == replacement_images["images/scene_001.png"]
    assert (
        project_directory / "images" / "scene_002.png"
    ).read_bytes() == replacement_images["images/scene_002.png"]
    assert (
        project_directory / "images" / "scene_003.png"
    ).read_bytes() == original_files["images/scene_003.png"]
    assert (
        project_directory / "storyboard" / "storyboard_audio_timed.json"
    ).read_bytes() == original_timed_storyboard
    assert (
        project_directory / "storyboard" / "storyboard_source.json"
    ).read_bytes() == original_source_storyboard
    assert package.script == (
        project_directory / "creative_input" / "script.txt"
    ).read_text(encoding="utf-8")


def test_image_override_rejects_changed_script_before_replacing_images(
    tmp_path,
):
    project, project_directory, original_files, _package = (
        _materialize_project_with_timed_storyboard(tmp_path)
    )
    original_image = (
        project_directory / "images" / "scene_001.png"
    ).read_bytes()
    override_zip = tmp_path / "changed-script.zip"
    _write_package(
        override_zip,
        project_id=project.project_id,
        script=original_files["script.txt"].decode("utf-8") + " Extra line.",
    )

    with pytest.raises(CreativePackageError, match="script differs"):
        apply_creative_image_overrides(
            project.project_id,
            project_directory,
            override_zip,
            ["scene_001"],
        )

    assert (
        project_directory / "images" / "scene_001.png"
    ).read_bytes() == original_image


def test_image_override_rejects_unknown_scene_ids_without_replacing_images(
    tmp_path,
):
    project, project_directory, original_files, _package = (
        _materialize_project_with_timed_storyboard(tmp_path)
    )
    override_zip = _write_override_package(
        tmp_path / "override.zip",
        original_files,
        {"images/scene_001.png": _png(1536, 864, color=(200, 30, 40))},
    )
    original_image = (
        project_directory / "images" / "scene_001.png"
    ).read_bytes()

    with pytest.raises(CreativePackageError, match="not present"):
        apply_creative_image_overrides(
            project.project_id,
            project_directory,
            override_zip,
            ["scene_999"],
        )

    assert (
        project_directory / "images" / "scene_001.png"
    ).read_bytes() == original_image


@pytest.mark.parametrize(
    ("mode", "stage", "release_tag", "scene_ids", "error"),
    [
        ("RESUME", "RENDER", "", "", None),
        ("RESUME", "RENDER", "fixed-images-v2", "scene_041,scene_042", None),
        ("NEW", "RENDER", "fixed-images-v2", "scene_041", "RESUME"),
        ("RESUME", "CONTINUE", "fixed-images-v2", "scene_041", "RENDER"),
        ("RESUME", "RENDER", "fixed-images-v2", "", "both"),
        ("RESUME", "RENDER", "", "scene_041", "both"),
    ],
)
def test_validates_optional_image_override_workflow_inputs(
    mode,
    stage,
    release_tag,
    scene_ids,
    error,
):
    if error is None:
        parsed = validate_image_override_inputs(
            mode=mode,
            rerun_from_stage=stage,
            release_tag=release_tag,
            scene_ids=scene_ids,
        )
        assert parsed == ([] if not scene_ids else ["scene_041", "scene_042"])
    else:
        with pytest.raises(ValueError, match=error):
            validate_image_override_inputs(
                mode=mode,
                rerun_from_stage=stage,
                release_tag=release_tag,
                scene_ids=scene_ids,
            )


def test_rejects_duplicate_or_malformed_image_override_scene_ids():
    with pytest.raises(ValueError, match="duplicates"):
        parse_scene_ids("scene_041,scene_041")

    with pytest.raises(ValueError, match="scene_NNN"):
        parse_scene_ids("41,scene_042")


def test_rejects_archive_above_configured_size_limit(tmp_path, monkeypatch):
    archive = tmp_path / "oversized.zip"
    _write_package(archive)
    monkeypatch.setattr(
        "modules.project.creative_package.CREATIVE_PACKAGE_MAX_ARCHIVE_BYTES",
        archive.stat().st_size - 1,
    )

    with pytest.raises(CreativePackageError, match="1 GiB archive-size limit"):
        load_creative_package(archive)


def test_rejects_expanded_contents_above_configured_size_limit(
    tmp_path,
    monkeypatch,
):
    archive = tmp_path / "oversized-expanded.zip"
    _write_package(archive)
    monkeypatch.setattr(
        "modules.project.creative_package.CREATIVE_PACKAGE_MAX_UNCOMPRESSED_BYTES",
        1,
    )

    with pytest.raises(
        CreativePackageError,
        match="1 GiB uncompressed-size limit",
    ):
        load_creative_package(archive)


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
    production_config = json.loads(
        (project_directory / "production_config.json").read_text(encoding="utf-8")
    )
    assert production_config["scene_minimum_duration_seconds"] == pytest.approx(0.0)
    assert production_config["scene_maximum_duration_seconds"] == pytest.approx(10.0)
    assert production_config["words_per_minute"] == 170
    assert production_config["voice_speed"] == pytest.approx(1.0)
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
    assert len(loaded_assets) == len(package.storyboard.scenes)
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


def test_rejects_script_sentences_over_15_words_before_creating_project(tmp_path):
    archive = tmp_path / "overlong-sentence.zip"
    long_sentence = " ".join(f"word{index}" for index in range(1, 17)) + "."
    script = f"{long_sentence} " + " ".join(["Brief."] * 154)
    _write_package(archive, script=script)
    package = load_creative_package(archive)

    with pytest.raises(
        CreativePackageError,
        match="SCRIPT_SENTENCE_TOO_LONG: sentence 1 has 16 words",
    ):
        materialize_creative_package(package, tmp_path / "projects")

    assert not (tmp_path / "projects").exists()


def test_accepts_short_script_sentence_before_creating_project(tmp_path):
    archive = tmp_path / "short-sentence.zip"
    short_sentence = "This short sentence has only nine spoken words today."
    remaining_sentences = [
        " ".join(f"word{index}" for index in range(start, start + 14)) + "."
        for start in range(1, 169, 14)
    ]
    script = " ".join([short_sentence, *remaining_sentences])
    _write_package(archive, script=script)
    package = load_creative_package(archive)

    project, _ = materialize_creative_package(package, tmp_path / "projects")

    assert project.project_id == package.manifest.project_id


def test_allows_one_word_sentence_pair_in_creative_script(tmp_path):
    archive = tmp_path / "paired-short-sentences.zip"
    normal_sentence = " ".join(f"spoken{index}" for index in range(10)) + "."
    script = "Go. Now. " + " ".join([normal_sentence] * 17)
    _write_package(archive, script=script)
    package = load_creative_package(archive)

    project, _ = materialize_creative_package(package, tmp_path / "projects")

    assert project.project_id == package.manifest.project_id


def test_rejects_insufficient_storyboard_scene_count_before_creating_project(tmp_path):
    archive = tmp_path / "too-few-scenes.zip"
    _write_package(archive, max_words_per_scene=140)
    package = load_creative_package(archive)

    with pytest.raises(
        CreativePackageError,
        match="STORYBOARD_SCENE_COUNT_TOO_LOW",
    ):
        materialize_creative_package(package, tmp_path / "projects")

    assert not (tmp_path / "projects").exists()


def test_accepts_more_than_200_scenes_within_archive_member_limit(tmp_path):
    archive = tmp_path / "more-than-200-scenes.zip"
    _write_package(
        archive,
        script=" ".join(["Narration."] * 210),
        max_words_per_scene=1,
    )

    package = load_creative_package(archive)

    assert len(package.storyboard.scenes) == 210


def test_rejects_storyboard_scene_excerpts_over_15_words(tmp_path):
    archive = tmp_path / "overlong-scene.zip"
    files = _write_package(archive)
    storyboard = json.loads(files["storyboard.json"])
    words = files["script.txt"].decode().split()
    storyboard["scenes"][0]["narration"] = " ".join(words[:16])
    storyboard["scenes"][1]["narration"] = " ".join(words[16:28])
    files["storyboard.json"] = json.dumps(storyboard).encode()
    with ZipFile(archive, "w") as output:
        for name, contents in files.items():
            output.writestr(name, contents)
    package = load_creative_package(archive)

    with pytest.raises(CreativePackageError, match="STORYBOARD_SCENE_TOO_LONG"):
        materialize_creative_package(package, tmp_path / "projects")

    assert not (tmp_path / "projects").exists()


def test_accepts_script_longer_than_target_without_upper_duration_limit(tmp_path):
    archive = tmp_path / "long-script.zip"
    script_words = ["narration"] * 281
    sentence_sizes = [14] * 19 + [15]
    sentences = []
    word_index = 0
    for sentence_size in sentence_sizes:
        sentences.append(
            " ".join(script_words[word_index : word_index + sentence_size]) + "."
        )
        word_index += sentence_size
    script = " ".join(sentences)
    _write_package(
        archive,
        script=script,
        overrides={"target_duration_minutes": 1},
    )
    package = load_creative_package(archive)

    _, project_directory = materialize_creative_package(
        package,
        tmp_path / "projects",
    )

    assert project_directory.is_dir()


def test_rejects_project_id_reuse_with_different_zip(tmp_path):
    projects = tmp_path / "projects"
    first_archive = tmp_path / "first.zip"
    _write_package(first_archive)
    first = load_creative_package(first_archive)
    materialize_creative_package(first, projects)

    second_archive = tmp_path / "second.zip"
    _write_package(
        second_archive,
        script=" ".join(
            [
                "Different supplied narration includes added words to satisfy "
                "script validation before project identity is checked."
            ]
            * 20
        ),
    )
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


def test_final_package_keeps_metadata_and_packages_processed_thumbnail(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("RITZZ_REMOVE_GEMINI_WATERMARK", "true")
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
        packaged_thumbnail = final_package.read("thumbnail.png")
        assert packaged_thumbnail != source_files["thumbnail.png"]
        assert struct.unpack(">II", packaged_thumbnail[16:24]) == (1280, 720)
        manifest = json.loads(final_package.read("package_manifest.json"))
        assert manifest["files_sha256"]["thumbnail.png"] == hashlib.sha256(
            packaged_thumbnail
        ).hexdigest()
        assert manifest["human_approval"] == "PENDING"
        assert manifest["qa_status"] == "REVIEW"
        assert manifest["technical_qa_status"] == "PASS"

    assert (
        (project_directory / "creative_input" / "thumbnail.png").read_bytes()
        == source_files["thumbnail.png"]
    )
    assert (
        (project_directory / "thumbnail" / "processed_thumbnail.png").read_bytes()
        == packaged_thumbnail
    )
    assert (video_directory / "thumbnail.png").read_bytes() == source_files[
        "thumbnail.png"
    ]

    approved_output = build_final_package(
        project_directory,
        tmp_path / "approved-package.zip",
        human_approval="APPROVED",
    )
    with ZipFile(approved_output) as final_package:
        manifest = json.loads(final_package.read("package_manifest.json"))
        assert manifest["human_approval"] == "APPROVED"
