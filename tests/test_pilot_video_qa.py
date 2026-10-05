import json
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.storyboard.models import Storyboard, StoryboardScene
from modules.video.models import VideoAssemblyPlan, VideoClip
from modules.video.pilot_qa import (
    OpenAIImageEditorialReviewer,
    PilotVideoQA,
    _mp3_duration,
)
from modules.video.qa_models import (
    AudioImageMatchResult,
    SceneQAResult,
)
from modules.video.render_models import AudioLoudnessMeasurement


def make_png():
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff")) + chunk(b"IEND", b""))


def make_inputs(tmp_path):
    image = tmp_path / "scene_001.png"
    image.write_bytes(make_png())
    storyboard = Storyboard(
        topic="Pirates",
        target_duration_seconds=2,
        total_scene_duration_seconds=2,
        scenes=[
            StoryboardScene(
                scene_id="scene_001",
                section_id="s1",
                start_seconds=0,
                duration_seconds=2,
                narration="Pirate narration.",
                visual_description="A pirate with an eye patch.",
                image_prompt="Pirate illustration.",
                text_overlay="ICONIC",
            )
        ],
    )
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
    assert result.checks["audio_loudness"] == "REVIEW"


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


def test_technical_qa_reports_in_range_audio_loudness(tmp_path, monkeypatch):
    storyboard, plan, audio, _ = make_inputs(tmp_path)
    video = tmp_path / "rendered.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        "modules.video.render_engine.FFmpegVideoRenderer.measure_audio_loudness",
        lambda self, path: AudioLoudnessMeasurement(
            integrated_lufs=-14.4,
            true_peak_dbtp=-1.1,
        ),
    )

    result = PilotVideoQA().run_technical(
        storyboard,
        plan,
        audio,
        video_file=video,
        audio_duration=2,
        video_duration=2,
    )

    assert result.checks["audio_loudness"] == "PASS"
    assert result.integrated_lufs == pytest.approx(-14.4)
    assert result.true_peak_dbtp == pytest.approx(-1.1)
    assert any("-14.4 LUFS integrated" in issue for issue in result.issues)


def test_technical_qa_accepts_audio_within_two_lu_of_target(tmp_path, monkeypatch):
    storyboard, plan, audio, _ = make_inputs(tmp_path)
    video = tmp_path / "rendered.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        "modules.video.render_engine.FFmpegVideoRenderer.measure_audio_loudness",
        lambda self, path: AudioLoudnessMeasurement(
            integrated_lufs=-15.9,
            true_peak_dbtp=-2.4,
        ),
    )

    result = PilotVideoQA().run_technical(
        storyboard,
        plan,
        audio,
        video_file=video,
        audio_duration=2,
        video_duration=2,
    )

    assert result.checks["audio_loudness"] == "PASS"
    assert result.status == "PASS"


@pytest.mark.parametrize(
    ("integrated_lufs", "true_peak_dbtp"),
    [(-16.1, -1.0), (-14.0, -0.8)],
)
def test_technical_qa_reviews_audio_outside_loudness_limits(
    tmp_path,
    monkeypatch,
    integrated_lufs,
    true_peak_dbtp,
):
    storyboard, plan, audio, _ = make_inputs(tmp_path)
    video = tmp_path / "rendered.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        "modules.video.render_engine.FFmpegVideoRenderer.measure_audio_loudness",
        lambda self, path: AudioLoudnessMeasurement(
            integrated_lufs=integrated_lufs,
            true_peak_dbtp=true_peak_dbtp,
        ),
    )

    result = PilotVideoQA().run_technical(
        storyboard,
        plan,
        audio,
        video_file=video,
        audio_duration=2,
        video_duration=2,
    )

    assert result.checks["audio_loudness"] == "REVIEW"
    assert result.status == "REVIEW"
    assert any("outside the configured target range" in issue for issue in result.issues)


def test_technical_qa_reviews_unmeasurable_audio(tmp_path, monkeypatch):
    storyboard, plan, audio, _ = make_inputs(tmp_path)
    video = tmp_path / "rendered.mp4"
    video.write_bytes(b"video")

    def unmeasurable(self, path):
        raise ValueError("audio is silent")

    monkeypatch.setattr(
        "modules.video.render_engine.FFmpegVideoRenderer.measure_audio_loudness",
        unmeasurable,
    )

    result = PilotVideoQA().run_technical(
        storyboard,
        plan,
        audio,
        video_file=video,
        audio_duration=2,
        video_duration=2,
    )

    assert result.checks["audio_loudness"] == "REVIEW"
    assert result.integrated_lufs is None
    assert result.true_peak_dbtp is None
    assert any("automatic audio correction" in issue for issue in result.issues)


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


def test_openai_rendered_scene_reviewer_requests_strict_json_schema(tmp_path):
    storyboard, _, _, image = make_inputs(tmp_path)
    captured = {}
    payload = {
        "narration_image": "PASS",
        "narration_description": "PASS",
        "editorial_context": "REVIEW",
        "rationale": "The word is hard to read.",
        "correction_prompt": None,
        "suggested_editorial_scene_id": None,
    }

    reviewer = OpenAIImageEditorialReviewer(api_key="test-key", model="test-model")

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            output_text=json.dumps(payload),
            status="completed",
            incomplete_details=None,
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(reviewer.client.responses, "create", fake_create)

    try:
        result = reviewer.review(image, storyboard.scenes[0])
    finally:
        monkeypatch.undo()

    assert result.status == "REVIEW"
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True
    assert captured["text"]["format"]["schema"]["additionalProperties"] is False


def test_openai_rendered_scene_reviewer_reports_empty_incomplete_output(tmp_path):
    storyboard, _, _, image = make_inputs(tmp_path)
    reviewer = OpenAIImageEditorialReviewer(api_key="test-key", model="test-model")

    def fake_create(**_kwargs):
        return SimpleNamespace(
            output_text="",
            status="incomplete",
            incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        )

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(reviewer.client.responses, "create", fake_create)

    try:
        with pytest.raises(
            ValueError,
            match=r"no structured output for scene_001 \(status=incomplete, incomplete_reason=max_output_tokens\)",
        ):
            reviewer.review(image, storyboard.scenes[0])
    finally:
        monkeypatch.undo()


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


def test_rendered_video_semantic_qa_reviews_frames_at_scene_midpoints(tmp_path, monkeypatch):
    storyboard, plan, _, _ = make_inputs(tmp_path)
    video = tmp_path / "rendered.mp4"
    video.write_bytes(b"video")
    seen = []

    def fake_run(command, **_kwargs):
        seen.append(command)
        Path(command[-1]).write_bytes(make_png())

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    class Reviewer:
        def review(self, image_path, scene):
            assert image_path.is_file()
            assert scene.narration == "Pirate narration."
            assert scene.text_overlay == "ICONIC"
            return SceneQAResult(
                scene_id=scene.scene_id,
                status="PASS",
                narration_image="PASS",
                narration_description="PASS",
                editorial_context="PASS",
                rationale="The rendered frame matches the aligned scene.",
            )

    monkeypatch.setattr("modules.video.pilot_qa.subprocess.run", fake_run)
    report = PilotVideoQA().run_rendered_video_semantic(
        storyboard,
        plan,
        video,
        Reviewer(),
        ffmpeg_path="ffmpeg-test",
    )

    assert report.status == "PASS"
    assert report.counts == {"PASS": 1, "REVIEW": 0, "FAIL": 0}
    assert "-ss" in seen[0]
    assert seen[0][seen[0].index("-ss") + 1] == "1.000"


def test_rendered_video_semantic_qa_receives_each_scene_narration_segment(tmp_path, monkeypatch):
    image = tmp_path / "scene_001.png"
    image.write_bytes(make_png())
    storyboard = Storyboard(
        topic="Pirates",
        target_duration_seconds=4,
        total_scene_duration_seconds=4,
        scenes=[
            StoryboardScene(
                scene_id="scene_001",
                section_id="s1",
                start_seconds=0,
                duration_seconds=2,
                narration="The pirate enters the dark cabin.",
                visual_description="A pirate entering a cabin.",
                image_prompt="Pirate illustration.",
            ),
            StoryboardScene(
                scene_id="scene_002",
                section_id="s1",
                start_seconds=2,
                duration_seconds=2,
                narration="One eye stays adapted to darkness.",
                visual_description="A pirate's adapted eye.",
                image_prompt="Eye illustration.",
            ),
        ],
    )
    plan = VideoAssemblyPlan(
        topic="Pirates",
        width=1920,
        height=1080,
        fps=30,
        clips=[
            VideoClip(scene_id=f"scene_{index:03}", image_path=str(image),
                      start_seconds=(index - 1) * 2, duration_seconds=2)
            for index in (1, 2)
        ],
        total_duration_seconds=4,
    )
    video = tmp_path / "rendered.mp4"
    video.write_bytes(b"video")

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(make_png())

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    reviewed_narration = []

    class Reviewer:
        def review(self, image_path, scene):
            reviewed_narration.append(scene.narration)
            return SceneQAResult(
                scene_id=scene.scene_id,
                status="REVIEW",
                narration_image="REVIEW",
                narration_description="PASS",
                editorial_context="PASS",
                rationale="Needs human review.",
            )

    monkeypatch.setattr("modules.video.pilot_qa.subprocess.run", fake_run)
    report = PilotVideoQA().run_rendered_video_semantic(
        storyboard,
        plan,
        video,
        Reviewer(),
        ffmpeg_path="ffmpeg-test",
    )

    assert reviewed_narration == [
        "The pirate enters the dark cabin.",
        "One eye stays adapted to darkness.",
    ]
    assert report.status == "REVIEW"


def test_mp3_duration_fallback_counts_frames(tmp_path):
    # MPEG-1 Layer III, 128 kbps, 44.1 kHz frames.
    frame = b"\xff\xfb\x90\x64" + bytes(413)
    audio = tmp_path / "sample.mp3"
    audio.write_bytes(frame * 4)
    assert _mp3_duration(audio) == pytest.approx(4 * 1152 / 44100)
