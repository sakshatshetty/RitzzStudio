import json
import zipfile

import pytest

from modules.storyboard.models import Storyboard
from modules.video.models import VideoAssemblyPlan, VideoClip
from modules.video.pro_director import (
    ProEditingDirector,
    prepare_sound_effects_archive,
)


def _storyboard() -> Storyboard:
    return Storyboard.model_validate(
        {
            "topic": "Test topic",
            "target_duration_seconds": 9,
            "total_scene_duration_seconds": 9,
            "scenes": [
                {
                    "scene_id": "scene_001",
                    "section_id": "setup",
                    "start_seconds": 0,
                    "duration_seconds": 3,
                    "narration": "Why does this happen?",
                    "visual_description": "A simple scene showing the question.",
                    "image_prompt": "Draw a clear simple scene.",
                },
                {
                    "scene_id": "scene_002",
                    "section_id": "reveal",
                    "start_seconds": 3,
                    "duration_seconds": 3,
                    "narration": "The answer reveals a hidden pattern.",
                    "visual_description": "A simple scene showing the pattern.",
                    "image_prompt": "Draw the revealed pattern.",
                    "text_overlay": "REVEAL",
                    "callout_position": "lower_right",
                },
                {
                    "scene_id": "scene_003",
                    "section_id": "reveal",
                    "start_seconds": 6,
                    "duration_seconds": 3,
                    "narration": "Then a sudden crash changes everything.",
                    "visual_description": "A simple scene showing the impact.",
                    "image_prompt": "Draw the change clearly.",
                },
            ],
        }
    )


def _assembly_plan() -> VideoAssemblyPlan:
    return VideoAssemblyPlan(
        topic="Test topic",
        width=320,
        height=180,
        fps=30,
        clips=[
            VideoClip(
                scene_id=f"scene_{index:03d}",
                image_path=f"scene_{index:03d}.png",
                start_seconds=(index - 1) * 3,
                duration_seconds=3,
            )
            for index in range(1, 4)
        ],
        total_duration_seconds=9,
    )


def _sound_effect_library(path):
    path.mkdir()
    (path / "whoosh.wav").write_bytes(b"whoosh")
    (path / "impact.wav").write_bytes(b"impact")
    (path / "manifest.json").write_text(
        json.dumps(
            {
                "effects": [
                    {"file": "whoosh.wav", "tags": ["transition", "whoosh"]},
                    {"file": "impact.wav", "tags": ["impact"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_director_chooses_section_fades_overlay_and_script_cued_sfx(
    tmp_path,
    monkeypatch,
):
    library = _sound_effect_library(tmp_path / "effects")
    monkeypatch.setattr(
        "modules.video.pro_director.detect_visible_text",
        lambda _path: (),
    )

    plan = ProEditingDirector().create_plan(
        _storyboard(),
        _assembly_plan(),
        library,
    )

    assert [scene.incoming_transition for scene in plan.scenes] == [
        "cut",
        "fade",
        "cut",
    ]
    assert plan.scenes[1].transition_duration_seconds == 0.3
    assert plan.scenes[1].overlay_text == "REVEAL"
    assert plan.scenes[1].overlay_position == "lower_right"
    assert [(event.cue, event.start_seconds) for event in plan.sound_effects] == [
        ("transition", 3),
        ("impact", 6),
    ]
    assert plan.sound_effects[0].file_path.endswith("whoosh.wav")
    assert plan.sound_effects[1].file_path.endswith("impact.wav")


def test_director_rejects_misaligned_storyboard_and_video_timeline(tmp_path):
    library = _sound_effect_library(tmp_path / "effects")
    assembly = _assembly_plan().model_copy(update={"topic": "Different topic"})

    with pytest.raises(ValueError, match="topic does not match"):
        ProEditingDirector().create_plan(_storyboard(), assembly, library)


def test_sound_effect_archive_is_validated_and_extracted_safely(tmp_path):
    archive = tmp_path / "library.zip"
    with zipfile.ZipFile(archive, "w") as sound_archive:
        sound_archive.writestr(
            "manifest.json",
            json.dumps(
                {"effects": [{"file": "sfx/whoosh.wav", "tags": ["transition"]}]}
            ),
        )
        sound_archive.writestr("sfx/whoosh.wav", b"audio bytes")

    output = prepare_sound_effects_archive(
        archive,
        tmp_path / "prepared",
    )

    assert (output / "manifest.json").is_file()
    assert (output / "sfx" / "whoosh.wav").read_bytes() == b"audio bytes"


def test_sound_effect_archive_accepts_more_than_256_files(tmp_path):
    archive = tmp_path / "large-library.zip"
    effects = [
        {"file": f"sfx/effect_{index:03d}.wav", "tags": ["transition"]}
        for index in range(300)
    ]
    with zipfile.ZipFile(archive, "w") as sound_archive:
        sound_archive.writestr(
            "manifest.json",
            json.dumps({"effects": effects}),
        )
        for effect in effects:
            sound_archive.writestr(effect["file"], b"audio bytes")

    output = prepare_sound_effects_archive(
        archive,
        tmp_path / "prepared",
    )

    assert len(list((output / "sfx").glob("*.wav"))) == 300


def test_sound_effect_archive_rejects_path_traversal(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as sound_archive:
        sound_archive.writestr("../outside.wav", b"not allowed")

    with pytest.raises(ValueError, match="Unsafe Pro sound-effects path"):
        prepare_sound_effects_archive(
            archive,
            tmp_path / "prepared",
        )

    assert not (tmp_path / "prepared").exists()
