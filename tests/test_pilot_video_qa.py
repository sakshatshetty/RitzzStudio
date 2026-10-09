import json
import struct
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.project.config import ProductionConfig
from modules.storyboard.models import Storyboard, StoryboardScene
from modules.storyboard.visual_models import VisualWorldBible
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
        target_duration_seconds=4,
        total_scene_duration_seconds=4,
        scenes=[
            StoryboardScene(
                scene_id="scene_001",
                section_id="s1",
                start_seconds=0,
                duration_seconds=4,
                narration="Pirate narration.",
                visual_description="A pirate with an eye patch.",
                image_prompt="Pirate illustration.",
                text_overlay="ICONIC",
                callout_position="lower_left",
            )
        ],
    )
    plan = VideoAssemblyPlan(topic="Pirates", width=16, height=16, fps=30,
        clips=[VideoClip(scene_id="scene_001", image_path=str(image), start_seconds=0, duration_seconds=4)],
        total_duration_seconds=4)
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    return storyboard, plan, audio, image


def test_technical_qa_checks_images_and_duration(tmp_path):
    storyboard, plan, audio, _ = make_inputs(tmp_path)
    result = PilotVideoQA().run_technical(storyboard, plan, audio, audio_duration=4)
    assert result.status == "REVIEW"  # video has not yet been rendered
    assert result.checks["images"] == "PASS"
    assert result.checks["timestamp_coverage"] == "PASS"
    assert result.checks["duration_consistency"] == "PASS"
    assert result.checks["audio_loudness"] == "REVIEW"


@pytest.mark.parametrize("duration", [2.0, 7.0, 10.0])
def test_technical_qa_does_not_reject_sentence_image_hold_lengths(
    tmp_path,
    duration,
):
    storyboard, plan, audio, _ = make_inputs(tmp_path)
    storyboard.scenes[0] = storyboard.scenes[0].model_copy(
        update={"duration_seconds": duration}
    )
    clip = plan.clips[0].model_copy(update={"duration_seconds": duration})
    sentence_plan = plan.model_copy(
        update={"clips": [clip], "total_duration_seconds": duration}
    )

    result = PilotVideoQA().run_technical(
        storyboard,
        sentence_plan,
        audio,
        audio_duration=duration,
        production_config=ProductionConfig(
            target_duration_seconds=480,
            minimum_duration_seconds=480,
            scene_minimum_duration_seconds=3,
            scene_maximum_duration_seconds=4,
        ),
    )

    assert result.checks["scene_durations"] == "PASS"
    assert result.checks["timestamp_coverage"] == "PASS"


def test_technical_qa_fails_when_rendered_video_duration_drifts_from_audio(tmp_path):
    storyboard, plan, audio, _ = make_inputs(tmp_path)
    video = tmp_path / "rendered.mp4"
    video.write_bytes(b"video")

    result = PilotVideoQA().run_technical(
        storyboard,
        plan,
        audio,
        video_file=video,
        audio_duration=4,
        video_duration=4.5,
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
        audio_duration=4,
        video_duration=4,
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
        audio_duration=4,
        video_duration=4,
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
        audio_duration=4,
        video_duration=4,
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
        audio_duration=4,
        video_duration=4,
    )

    assert result.checks["audio_loudness"] == "REVIEW"
    assert result.integrated_lufs is None
    assert result.true_peak_dbtp is None
    assert any("automatic audio correction" in issue for issue in result.issues)


def test_technical_qa_flags_corrupt_image(tmp_path):
    storyboard, plan, audio, image = make_inputs(tmp_path)
    image.write_bytes(b"not a png")
    result = PilotVideoQA().run_technical(storyboard, plan, audio, audio_duration=4)
    assert result.status == "FAIL"
    assert result.checks["images"] == "FAIL"


def test_technical_qa_reports_large_storyboard_drift(tmp_path):
    storyboard, plan, audio, _ = make_inputs(tmp_path)
    storyboard.scenes[0].start_seconds = 1.0
    result = PilotVideoQA().run_technical(storyboard, plan, audio, audio_duration=4)
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
        "scene_id": "scene_001",
        "narration_image": "PASS",
        "narration_description": "PASS",
        "unwanted_text": "PASS",
        "rationale": "The illustration matches the narration and scene intent.",
        "correction_prompt": None,
        "failure_category": None,
    }

    world = VisualWorldBible(
        topic="Test Topic",
        historical=True,
        time_period="1200 CE",
        geography="Coastal settlement",
        civilization_or_society="Medieval port community",
        technology_level="Hand-powered tools",
        built_environment="Timber buildings",
        clothing="Wool and linen",
        transportation="Sailing vessels",
        tools_and_weapons="Hand tools",
        containers_and_materials="Wood and pottery",
        architecture="Timber structures",
        natural_environment="Rocky coast",
        social_context="Small port community",
        visual_style="Simple 2D cartoon",
        technology_ceiling="No powered machinery.",
    )
    reviewer = OpenAIImageEditorialReviewer(
        api_key="test-key",
        model="test-model",
        visual_world=world,
    )

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

    assert result.status == "PASS"
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True
    assert captured["text"]["format"]["schema"]["additionalProperties"] is False
    assert "technology_ceiling" in captured["input"][0]["content"][0]["text"]
    assert "failure_category" in captured["text"]["format"]["schema"]["required"]
    assert "unwanted_text" in captured["text"]["format"]["schema"]["required"]
    assert "editorial_text" not in captured["text"]["format"]["schema"]["properties"]
    assert "editorial_context" not in captured["input"][0]["content"][0]["text"]
    assert "garbled lettering" in captured["input"][0]["content"][0]["text"]
    assert "consistent RITZZ 2D line art" in captured["input"][0]["content"][0]["text"]
    assert "no exceptions for text on physical objects" in captured["input"][0]["content"][0]["text"]
    assert "intentional context transition" in captured["input"][0]["content"][0]["text"]
    assert result.editorial_context == "PASS"
    assert result.unwanted_text == "PASS"


def test_openai_rendered_scene_reviewer_preserves_failure_category(
    tmp_path,
    monkeypatch,
):
    storyboard, _, _, image = make_inputs(tmp_path)
    payload = {
        "scene_id": "scene_001",
        "narration_image": "FAIL",
        "narration_description": "PASS",
        "unwanted_text": "PASS",
        "rationale": "The scene action is not visible.",
        "correction_prompt": "Show the described action clearly.",
        "failure_category": "WRONG_ACTION",
    }
    reviewer = OpenAIImageEditorialReviewer(api_key="test-key", model="test-model")
    monkeypatch.setattr(
        reviewer.client.responses,
        "create",
        lambda **_kwargs: SimpleNamespace(
            output_text=json.dumps(payload),
            status="completed",
            incomplete_details=None,
        ),
    )

    result = reviewer.review(image, storyboard.scenes[0])

    assert result.status == "FAIL"
    assert result.failure_category == "WRONG_ACTION"
    assert result.editorial_context == "PASS"


def test_openai_rendered_scene_reviewer_flags_editorial_text(
    tmp_path,
    monkeypatch,
):
    storyboard, _, _, image = make_inputs(tmp_path)
    payload = {
        "scene_id": "scene_001",
        "narration_image": "PASS",
        "narration_description": "PASS",
        "unwanted_text": "FAIL",
        "rationale": "A misspelled editorial word is visible.",
        "correction_prompt": "Remove all text from the illustration.",
        "failure_category": "UNWANTED_TEXT",
    }
    reviewer = OpenAIImageEditorialReviewer(api_key="test-key", model="test-model")
    monkeypatch.setattr(
        reviewer.client.responses,
        "create",
        lambda **_kwargs: SimpleNamespace(
            output_text=json.dumps(payload),
            status="completed",
            incomplete_details=None,
        ),
    )

    result = reviewer.review(image, storyboard.scenes[0])

    assert result.status == "FAIL"
    assert result.unwanted_text == "FAIL"
    assert result.failure_category == "UNWANTED_TEXT"


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


def test_openai_rendered_scene_batch_preserves_full_narration_and_order(tmp_path):
    storyboard, _, _, image = make_inputs(tmp_path)
    storyboard.scenes[0] = storyboard.scenes[0].model_copy(
        update={
            "sentence_id": 1,
            "sentence": "Pirate narration.",
            "previous_sentence": "The ship leaves port.",
            "next_sentence": "The sailor looks toward the horizon.",
        }
    )
    second_image = tmp_path / "scene_002.png"
    second_image.write_bytes(make_png())
    second_scene = storyboard.scenes[0].model_copy(update={
        "scene_id": "scene_002",
        "narration": "The complete second scene narration.",
        "sentence_id": 2,
        "sentence": "The complete second scene narration.",
        "previous_sentence": "Pirate narration.",
        "next_sentence": "A new event follows.",
        "start_seconds": 2,
    })
    captured = {}
    payload = {
        "scenes": [
            {
                "scene_id": scene.scene_id,
                "narration_image": "PASS",
                "narration_description": "PASS",
                "unwanted_text": "PASS",
                "editorial_context": "PASS",
                "editorial_text": "PASS",
                "editorial_style": "PASS",
                "editorial_placement": "PASS",
                "editorial_obstruction": "PASS",
                "editorial_safe_space": "PASS",
                "rationale": "The image fits.",
                "correction_prompt": None,
                "suggested_editorial_scene_id": None,
                "suggested_editorial_position": None,
                "failure_category": None,
            }
            for scene in (storyboard.scenes[0], second_scene)
        ]
    }
    reviewer = OpenAIImageEditorialReviewer(api_key="test-key", model="test-model")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        reviewer.client.responses,
        "create",
        lambda **kwargs: (
            captured.update(kwargs)
            or SimpleNamespace(
                output_text=json.dumps(payload),
                status="completed",
                incomplete_details=None,
            )
        ),
    )

    try:
        results = reviewer.review_batch([
            (image, storyboard.scenes[0], []),
            (second_image, second_scene, []),
        ])
    finally:
        monkeypatch.undo()

    assert [result.scene_id for result in results] == ["scene_001", "scene_002"]
    assert "Pirate narration." in captured["input"][0]["content"][1]["text"]
    assert "Current sentence (primary visual target): Pirate narration." in captured["input"][0]["content"][1]["text"]
    assert "Previous sentence (continuity context only): The ship leaves port." in captured["input"][0]["content"][1]["text"]
    assert "Next sentence (continuity context only): The sailor looks toward the horizon." in captured["input"][0]["content"][1]["text"]
    assert "The complete second scene narration." in captured["input"][0]["content"][3]["text"]
    schema = captured["text"]["format"]["schema"]
    assert captured["text"]["format"]["strict"] is True
    assert schema["additionalProperties"] is False
    assert schema["properties"]["scenes"]["items"]["additionalProperties"] is False
    assert "failure_category" in schema["properties"]["scenes"]["items"]["required"]


def test_openai_rendered_scene_batch_rejects_reordered_scene_ids(tmp_path):
    storyboard, _, _, image = make_inputs(tmp_path)
    second_image = tmp_path / "scene_002.png"
    second_image.write_bytes(make_png())
    second_scene = storyboard.scenes[0].model_copy(update={
        "scene_id": "scene_002",
        "narration": "Second scene.",
        "start_seconds": 2,
    })
    payload = {
        "scenes": [
            {
                "scene_id": scene_id,
                "narration_image": "PASS",
                "narration_description": "PASS",
                "editorial_context": "PASS",
                "editorial_text": "PASS",
                "editorial_style": "PASS",
                "editorial_placement": "PASS",
                "editorial_obstruction": "PASS",
                "editorial_safe_space": "PASS",
                "rationale": "The image fits.",
                "correction_prompt": None,
                "suggested_editorial_scene_id": None,
                "suggested_editorial_position": None,
                "failure_category": None,
            }
            for scene_id in ("scene_002", "scene_001")
        ]
    }
    reviewer = OpenAIImageEditorialReviewer(api_key="test-key", model="test-model")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        reviewer.client.responses,
        "create",
        lambda **_kwargs: SimpleNamespace(
            output_text=json.dumps(payload),
            status="completed",
            incomplete_details=None,
        ),
    )

    try:
        with pytest.raises(ValueError, match="scene IDs do not match request ordering"):
            reviewer.review_batch([
                (image, storyboard.scenes[0], []),
                (second_image, second_scene, []),
            ])
    finally:
        monkeypatch.undo()


def test_audio_image_match_uses_synchronized_scene_range(tmp_path):
    storyboard, plan, _, _ = make_inputs(tmp_path)
    storyboard.scenes[0].sentence = "Pirate narration."
    storyboard.scenes[0].previous_sentence = "The ship leaves port."
    storyboard.scenes[0].next_sentence = "The sailor looks at the horizon."
    class Reviewer:
        def match_audio_image(self, image_path, scene, start_seconds, end_seconds):
            assert scene.narration == "Pirate narration."
            assert scene.previous_sentence == "The ship leaves port."
            assert scene.next_sentence == "The sailor looks at the horizon."
            return AudioImageMatchResult(scene_id=scene.scene_id, status="PASS", narration=scene.narration,
                start_seconds=start_seconds, end_seconds=end_seconds, rationale="Image matches the narration.")
    results = PilotVideoQA().run_audio_image_match(storyboard, plan, Reviewer())
    assert results[0].start_seconds == 0
    assert results[0].end_seconds == 4
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
    assert seen[0][seen[0].index("-ss") + 1] == "2.000"


def test_rendered_video_semantic_qa_receives_each_scene_narration_segment(tmp_path, monkeypatch):
    image = tmp_path / "scene_001.png"
    image.write_bytes(make_png())
    storyboard = Storyboard(
        topic="Pirates",
        target_duration_seconds=8,
        total_scene_duration_seconds=8,
        scenes=[
            StoryboardScene(
                scene_id="scene_001",
                section_id="s1",
                start_seconds=0,
                duration_seconds=4,
                narration="The pirate enters the dark cabin.",
                visual_description="A pirate entering a cabin.",
                image_prompt="Pirate illustration.",
            ),
            StoryboardScene(
                scene_id="scene_002",
                section_id="s1",
                start_seconds=4,
                duration_seconds=4,
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
                      start_seconds=(index - 1) * 4, duration_seconds=4)
            for index in (1, 2)
        ],
        total_duration_seconds=8,
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
