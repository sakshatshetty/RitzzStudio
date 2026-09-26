import base64
import json
import struct
import zlib
from pathlib import Path

import pytest

from modules.storyboard.models import Storyboard
from modules.video.models import VideoAssemblyPlan, VideoClip
from modules.video.pilot_qa import PilotVideoQA, _mp3_duration
from modules.video.qa_models import AudioImageMatchResult, SceneQAResult

def make_png():
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff")) + chunk(b"IEND", b""))


def make_inputs(tmp_path):
    image = tmp_path / "scene_001.png"
    image.write_bytes(make_png())
    storyboard = Storyboard(topic="Pirates", target_duration_seconds=2, total_scene_duration_seconds=2,
        scenes=[{"scene_id": "scene_001", "section_id": "s1", "start_seconds": 0, "duration_seconds": 2,
            "narration": "Pirate narration.", "visual_description": "A pirate with an eye patch.",
            "image_prompt": "Pirate illustration.", "text_overlay": "ICONIC"}])
    plan = VideoAssemblyPlan(topic="Pirates", width=16, height=16, fps=30,
        clips=[VideoClip(scene_id="scene_001", image_path=str(image), start_seconds=0, duration_seconds=2)],
        total_duration_seconds=2)
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    return storyboard, plan, audio, image


def test_technical_qa_checks_images_and_duration(tmp_path):
    storyboard, plan, audio, _ = make_inputs(tmp_path)
    result = PilotVideoQA().run_technical(storyboard, plan, audio, audio_duration=2)
    assert result.status == "REVIEW"  # video has not yet been rendered
    assert result.checks["images"] == "PASS"
    assert result.checks["timestamp_coverage"] == "PASS"
    assert result.checks["duration_consistency"] == "PASS"


def test_technical_qa_fails_when_rendered_video_duration_drifts_from_audio(tmp_path):
    storyboard, plan, audio, _ = make_inputs(tmp_path)
    video = tmp_path / "rendered.mp4"
    video.write_bytes(b"video")

    result = PilotVideoQA().run_technical(
        storyboard,
        plan,
        audio,
        video_file=video,
        audio_duration=2,
        video_duration=2.5,
    )

    assert result.status == "FAIL"
    assert result.checks["video"] == "FAIL"
    assert any("duration/streams do not match audio" in issue for issue in result.issues)


def test_technical_qa_flags_corrupt_image(tmp_path):
    storyboard, plan, audio, image = make_inputs(tmp_path)
    image.write_bytes(b"not a png")
    result = PilotVideoQA().run_technical(storyboard, plan, audio, audio_duration=2)
    assert result.status == "FAIL"
    assert result.checks["images"] == "FAIL"


def test_technical_qa_reports_large_storyboard_drift(tmp_path):
    storyboard, plan, audio, _ = make_inputs(tmp_path)
    storyboard.scenes[0].start_seconds = 1.0
    result = PilotVideoQA().run_technical(storyboard, plan, audio, audio_duration=2)
    assert result.checks["timeline_drift"] == "REVIEW"
    assert result.maximum_timeline_drift_seconds == pytest.approx(1.0)


def test_semantic_qa_preserves_scene_review_classification(tmp_path):
    storyboard, plan, _, _ = make_inputs(tmp_path)
    class Reviewer:
        def review(self, image_path, scene):
            assert scene.text_overlay == "ICONIC"
            return SceneQAResult(scene_id=scene.scene_id, status="REVIEW", narration_image="REVIEW",
                narration_description="PASS", editorial_context="REVIEW", rationale="Human review recommended.")
    results = PilotVideoQA().run_semantic(storyboard, plan, Reviewer())
    assert results[0].status == "REVIEW"


def test_audio_image_match_uses_synchronized_scene_range(tmp_path):
    storyboard, plan, _, _ = make_inputs(tmp_path)
    class Reviewer:
        def match_audio_image(self, image_path, scene, start_seconds, end_seconds):
            assert scene.narration == "Pirate narration."
            return AudioImageMatchResult(scene_id=scene.scene_id, status="PASS", narration=scene.narration,
                start_seconds=start_seconds, end_seconds=end_seconds, rationale="Image matches the narration.")
    results = PilotVideoQA().run_audio_image_match(storyboard, plan, Reviewer())
    assert results[0].start_seconds == 0
    assert results[0].end_seconds == 2
    assert results[0].status == "PASS"


def test_mp3_duration_fallback_counts_frames(tmp_path):
    # MPEG-1 Layer III, 128 kbps, 44.1 kHz frames.
    frame = b"\xff\xfb\x90\x64" + bytes(413)
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(frame * 4)
    assert _mp3_duration(audio) == pytest.approx(4 * 1152 / 44100)
