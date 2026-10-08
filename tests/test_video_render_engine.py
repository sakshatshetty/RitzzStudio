import math
import shutil
import subprocess
from pathlib import Path

import pytest

from modules.video.models import VideoAssemblyPlan, VideoClip
from modules.video.motion_models import (
    MotionInstruction,
    VideoMotionPlan,
)
from modules.video.render_engine import (
    FFmpegVideoRenderer,
)
from modules.video.render_models import VideoRenderRequest

FFMPEG_AVAILABLE = (
    shutil.which("ffmpeg") is not None
    and shutil.which("ffprobe") is not None
)


pytestmark = pytest.mark.skipif(
    not FFMPEG_AVAILABLE,
    reason="FFmpeg/ffprobe not available",
)


def create_test_images(
    tmp_path: Path,
) -> list[Path]:
    """
    Create three valid PNG images using FFmpeg.
    """

    ffmpeg = shutil.which("ffmpeg")

    assert ffmpeg is not None

    colors = [
        "red",
        "green",
        "blue",
    ]

    paths: list[Path] = []

    for index, color in enumerate(
        colors,
        start=1,
    ):
        output_file = (
            tmp_path
            / f"scene_{index:03d}.png"
        )

        command = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x180",
            "-frames:v",
            "1",
            str(output_file),
        ]

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0
        assert output_file.exists()
        assert output_file.stat().st_size > 0

        paths.append(
            output_file
        )

    return paths


def create_test_audio(
    tmp_path: Path,
    duration_seconds: float = 3.0,
    channels: int = 1,
) -> Path:
    """Create a valid mono sine-wave WAV file for rendering tests."""

    output_file = (
        tmp_path
        / "narration.wav"
    )
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None
    completed = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={duration_seconds}",
            "-ac",
            str(channels),
            "-c:a",
            "pcm_s16le",
            str(output_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr

    return output_file


def create_assembly_plan(
    image_paths: list[Path],
) -> VideoAssemblyPlan:
    return VideoAssemblyPlan(
        topic="Render Test",
        width=320,
        height=180,
        fps=30,
        clips=[
            VideoClip(
                scene_id="scene_001",
                image_path=str(
                    image_paths[0]
                ),
                start_seconds=0.0,
                duration_seconds=1.0,
                status="ready",
            ),
            VideoClip(
                scene_id="scene_002",
                image_path=str(
                    image_paths[1]
                ),
                start_seconds=1.0,
                duration_seconds=1.0,
                status="ready",
            ),
            VideoClip(
                scene_id="scene_003",
                image_path=str(
                    image_paths[2]
                ),
                start_seconds=2.0,
                duration_seconds=1.0,
                status="ready",
            ),
        ],
        total_duration_seconds=3.0,
        audio_path="narration.wav",
    )


def create_motion_plan() -> VideoMotionPlan:
    return VideoMotionPlan(
        topic="Render Test",
        width=320,
        height=180,
        fps=30,
        instructions=[
            MotionInstruction(
                scene_id="scene_001",
                start_seconds=0.0,
                duration_seconds=1.0,
                motion="slow_zoom_in",
                zoom_start=1.0,
                zoom_end=1.1,
                position_x_start=0.5,
                position_x_end=0.5,
                position_y_start=0.5,
                position_y_end=0.5,
            ),
            MotionInstruction(
                scene_id="scene_002",
                start_seconds=1.0,
                duration_seconds=1.0,
                motion="pan_right",
                zoom_start=1.1,
                zoom_end=1.1,
                position_x_start=0.4,
                position_x_end=0.6,
                position_y_start=0.5,
                position_y_end=0.5,
            ),
            MotionInstruction(
                scene_id="scene_003",
                start_seconds=2.0,
                duration_seconds=1.0,
                motion="static",
                zoom_start=1.0,
                zoom_end=1.0,
                position_x_start=0.5,
                position_x_end=0.5,
                position_y_start=0.5,
                position_y_end=0.5,
            ),
        ],
        total_duration_seconds=3.0,
    )


def test_create_request(
    tmp_path: Path,
) -> None:
    renderer = FFmpegVideoRenderer()

    request = renderer.create_request(
        tmp_path / "assembly.json",
        tmp_path / "motion.json",
        tmp_path / "output.mp4",
        tmp_path / "narration.wav",
    )

    assert isinstance(
        request,
        VideoRenderRequest,
    )

    assert request.assembly_plan_file == str(
        tmp_path / "assembly.json"
    )

    assert request.motion_plan_file == str(
        tmp_path / "motion.json"
    )

    assert request.output_file == str(
        tmp_path / "output.mp4"
    )

    assert request.audio_file == str(
        tmp_path / "narration.wav"
    )


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("10M", 10_000_000), ("8M", 8_000_000), ("900k", 900_000), ("10000000", 10_000_000)],
)
def test_video_bitrate_is_configurable(configured, expected, monkeypatch):
    monkeypatch.setenv("RITZZ_VIDEO_BITRATE", configured)

    renderer = FFmpegVideoRenderer()

    assert renderer.video_bitrate == configured
    assert renderer.video_bitrate_bps == expected


def test_video_bitrate_configuration_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("RITZZ_VIDEO_BITRATE", "fast")

    with pytest.raises(ValueError, match="RITZZ_VIDEO_BITRATE"):
        FFmpegVideoRenderer()


def test_audio_loudness_settings_are_configurable(monkeypatch):
    monkeypatch.setenv("RITZZ_AUDIO_TARGET_LUFS", "-16.5")
    monkeypatch.setenv("RITZZ_AUDIO_TRUE_PEAK_CEILING_DBTP", "-1.5")

    renderer = FFmpegVideoRenderer()

    assert renderer.audio_target_lufs == -16.5
    assert renderer.audio_true_peak_ceiling_dbtp == -1.5
    assert renderer.build_audio_filter() == (
        "acompressor=threshold=0.05:ratio=20:attack=5:release=100:makeup=1,"
        "loudnorm=I=-16.5:TP=-2.5:LRA=11"
    )


def test_audio_filter_tightens_true_peak_target_from_measured_qa():
    renderer = FFmpegVideoRenderer()

    adjustments = renderer.adjust_audio_filter_from_measurement(
        integrated_lufs=-15.1,
        true_peak_dbtp=-0.7,
        loudness_tolerance_lu=1.5,
        true_peak_tolerance_db=0.1,
    )

    assert renderer.audio_target_lufs == -14.0
    assert renderer.audio_filter_target_lufs == -14.0
    assert renderer.audio_true_peak_ceiling_dbtp == -1.0
    assert renderer.audio_filter_true_peak_target_dbtp == pytest.approx(-2.7)
    assert adjustments == ["loudnorm true-peak target -2.0 -> -2.7 dBTP"]
    assert "loudnorm=I=-14:TP=-2.7:LRA=11" in renderer.build_audio_filter()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RITZZ_AUDIO_TARGET_LUFS", "loud"),
        ("RITZZ_AUDIO_TARGET_LUFS", "-80"),
        ("RITZZ_AUDIO_TRUE_PEAK_CEILING_DBTP", "2"),
    ],
)
def test_invalid_audio_loudness_settings_are_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        FFmpegVideoRenderer()


def test_filter_script_contains_concat() -> None:
    renderer = FFmpegVideoRenderer()

    assembly_plan = VideoAssemblyPlan(
        topic="Test",
        width=320,
        height=180,
        fps=30,
        clips=[
            VideoClip(
                scene_id="scene_001",
                image_path="one.png",
                start_seconds=0.0,
                duration_seconds=1.0,
            ),
            VideoClip(
                scene_id="scene_002",
                image_path="two.png",
                start_seconds=1.0,
                duration_seconds=1.0,
            ),
        ],
        total_duration_seconds=2.0,
    )

    motion_plan = VideoMotionPlan(
        topic="Test",
        width=320,
        height=180,
        fps=30,
        instructions=[
            MotionInstruction(
                scene_id="scene_001",
                start_seconds=0.0,
                duration_seconds=1.0,
                motion="static",
                zoom_start=1.0,
                zoom_end=1.0,
                position_x_start=0.5,
                position_x_end=0.5,
                position_y_start=0.5,
                position_y_end=0.5,
            ),
            MotionInstruction(
                scene_id="scene_002",
                start_seconds=1.0,
                duration_seconds=1.0,
                motion="static",
                zoom_start=1.0,
                zoom_end=1.0,
                position_x_start=0.5,
                position_x_end=0.5,
                position_y_start=0.5,
                position_y_end=0.5,
            ),
        ],
        total_duration_seconds=2.0,
    )

    filter_script = (
        renderer.build_filter_script(
            assembly_plan,
            motion_plan,
        )
    )

    assert "concat=n=2:v=1:a=0" in (
        filter_script
    )

    assert "[vout]" in (
        filter_script
    )

    assert "zoompan" not in filter_script
    assert "loop=loop=-1" in filter_script


def test_filter_script_contains_zoompan() -> None:
    renderer = FFmpegVideoRenderer()

    assembly_plan = VideoAssemblyPlan(
        topic="Test",
        width=320,
        height=180,
        fps=30,
        clips=[
            VideoClip(
                scene_id="scene_001",
                image_path="one.png",
                start_seconds=0.0,
                duration_seconds=1.0,
            )
        ],
        total_duration_seconds=1.0,
    )

    motion_plan = VideoMotionPlan(
        topic="Test",
        width=320,
        height=180,
        fps=30,
        instructions=[
            MotionInstruction(
                scene_id="scene_001",
                start_seconds=0.0,
                duration_seconds=1.0,
                motion="slow_zoom_in",
                zoom_start=1.0,
                zoom_end=1.1,
                position_x_start=0.5,
                position_x_end=0.5,
                position_y_start=0.5,
                position_y_end=0.5,
            )
        ],
        total_duration_seconds=1.0,
    )

    filter_script = (
        renderer.build_filter_script(
            assembly_plan,
            motion_plan,
        )
    )

    assert "zoompan=" in (
        filter_script
    )

    assert "fps=30" in (
        filter_script
    )


def test_static_scene_frames_use_cumulative_sentence_cut_timestamps() -> None:
    renderer = FFmpegVideoRenderer()
    assembly_plan = VideoAssemblyPlan(
        topic="Sentence cuts",
        width=320,
        height=180,
        fps=30,
        clips=[
            VideoClip(
                scene_id="scene_001",
                image_path="one.png",
                start_seconds=0,
                duration_seconds=1.01,
            ),
            VideoClip(
                scene_id="scene_002",
                image_path="two.png",
                start_seconds=1.01,
                duration_seconds=0.21,
            ),
        ],
        total_duration_seconds=1.22,
    )
    motion_plan = VideoMotionPlan(
        topic="Sentence cuts",
        width=320,
        height=180,
        fps=30,
        instructions=[
            MotionInstruction(
                scene_id=clip.scene_id,
                start_seconds=clip.start_seconds,
                duration_seconds=clip.duration_seconds,
                motion="static",
                zoom_start=1,
                zoom_end=1,
                position_x_start=0.5,
                position_x_end=0.5,
                position_y_start=0.5,
                position_y_end=0.5,
            )
            for clip in assembly_plan.clips
        ],
        total_duration_seconds=1.22,
    )

    filter_script = renderer.build_filter_script(assembly_plan, motion_plan)

    assert "trim=end_frame=30" in filter_script
    assert "trim=end_frame=7" in filter_script
    assert "concat=n=2:v=1:a=0" in filter_script


def test_plan_mismatch_fails() -> None:
    renderer = FFmpegVideoRenderer()

    assembly_plan = VideoAssemblyPlan(
        topic="One",
        width=320,
        height=180,
        fps=30,
        clips=[
            VideoClip(
                scene_id="scene_001",
                image_path="one.png",
                start_seconds=0.0,
                duration_seconds=1.0,
            )
        ],
        total_duration_seconds=1.0,
    )

    motion_plan = VideoMotionPlan(
        topic="Two",
        width=320,
        height=180,
        fps=30,
        instructions=[
            MotionInstruction(
                scene_id="scene_001",
                start_seconds=0.0,
                duration_seconds=1.0,
                motion="static",
                zoom_start=1.0,
                zoom_end=1.0,
                position_x_start=0.5,
                position_x_end=0.5,
                position_y_start=0.5,
                position_y_end=0.5,
            )
        ],
        total_duration_seconds=1.0,
    )

    with pytest.raises(
        ValueError,
        match="topic",
    ):
        renderer.build_filter_script(
            assembly_plan,
            motion_plan,
        )


@pytest.mark.parametrize("audio_channels", [1, 2])
def test_render_three_scene_video(
    tmp_path: Path,
    audio_channels: int,
) -> None:
    images = create_test_images(
        tmp_path
    )

    audio = create_test_audio(
        tmp_path,
        duration_seconds=3.0,
        channels=audio_channels,
    )
    source_audio_bytes = audio.read_bytes()

    assembly_plan = (
        create_assembly_plan(
            images
        )
    )

    assembly_plan = (
        assembly_plan.model_copy(
            update={
                "audio_path": str(
                    audio
                )
            }
        )
    )

    motion_plan = create_motion_plan()

    output_file = (
        tmp_path
        / "ritzz_test.mp4"
    )

    renderer = FFmpegVideoRenderer()

    rendered = renderer.render(
        assembly_plan=assembly_plan,
        motion_plan=motion_plan,
        audio_file=audio,
        output_file=output_file,
    )

    assert rendered.exists()
    assert rendered.stat().st_size > 0

    probe = renderer._probe_media(
        rendered
    )

    assert probe["has_video"]
    assert probe["has_audio"]
    assert probe["audio_channels"] == audio_channels
    assert probe["video_codec_name"] == "h264"
    assert audio.read_bytes() == source_audio_bytes
    assert 8_000_000 <= probe["video_bit_rate_bps"] <= 12_000_000
    assert probe["audio_duration_seconds"] == pytest.approx(3.0, abs=0.25)

    assert probe["width"] == 320
    assert probe["height"] == 180

    assert math.isclose(
        probe["fps"],
        30.0,
        abs_tol=0.1,
    )

    assert probe[
        "duration_seconds"
    ] == pytest.approx(
        3.0,
        abs=0.25,
    )
    loudness = renderer.measure_audio_loudness(rendered)
    assert abs(loudness.integrated_lufs - renderer.audio_target_lufs) <= 1.5
    assert loudness.true_peak_dbtp <= renderer.audio_true_peak_ceiling_dbtp + 0.1


def test_default_production_render_is_exactly_1080p_30fps_16_9(
    tmp_path: Path,
) -> None:
    image = create_test_images(tmp_path)[0]
    audio = create_test_audio(tmp_path, duration_seconds=1.0)
    assembly_plan = VideoAssemblyPlan(
        topic="Production format",
        clips=[
            VideoClip(
                scene_id="scene_001",
                image_path=str(image),
                start_seconds=0.0,
                duration_seconds=1.0,
            )
        ],
        total_duration_seconds=1.0,
        audio_path=str(audio),
    )
    motion_plan = VideoMotionPlan(
        topic="Production format",
        width=1920,
        height=1080,
        fps=30,
        instructions=[
            MotionInstruction(
                scene_id="scene_001",
                start_seconds=0.0,
                duration_seconds=1.0,
                motion="static",
                zoom_start=1.0,
                zoom_end=1.0,
                position_x_start=0.5,
                position_x_end=0.5,
                position_y_start=0.5,
                position_y_end=0.5,
            )
        ],
        total_duration_seconds=1.0,
    )
    output = tmp_path / "production_format.mp4"
    renderer = FFmpegVideoRenderer()

    renderer.render(assembly_plan, motion_plan, audio, output)
    probe = renderer._probe_media(output)

    assert probe["width"] == 1920
    assert probe["height"] == 1080
    assert probe["width"] * 9 == probe["height"] * 16
    assert probe["fps"] == 30.0
    assert probe["video_codec_name"] == "h264"
    assert 8_000_000 <= probe["video_bit_rate_bps"] <= 12_000_000


def test_missing_image_fails(
    tmp_path: Path,
) -> None:
    renderer = FFmpegVideoRenderer()

    assembly_plan = VideoAssemblyPlan(
        topic="Test",
        width=320,
        height=180,
        fps=30,
        clips=[
            VideoClip(
                scene_id="scene_001",
                image_path=str(
                    tmp_path
                    / "missing.png"
                ),
                start_seconds=0.0,
                duration_seconds=1.0,
            )
        ],
        total_duration_seconds=1.0,
    )

    motion_plan = VideoMotionPlan(
        topic="Test",
        width=320,
        height=180,
        fps=30,
        instructions=[
            MotionInstruction(
                scene_id="scene_001",
                start_seconds=0.0,
                duration_seconds=1.0,
                motion="static",
                zoom_start=1.0,
                zoom_end=1.0,
                position_x_start=0.5,
                position_x_end=0.5,
                position_y_start=0.5,
                position_y_end=0.5,
            )
        ],
        total_duration_seconds=1.0,
    )

    with pytest.raises(
        FileNotFoundError,
    ):
        renderer.render(
            assembly_plan,
            motion_plan,
            tmp_path / "audio.wav",
            tmp_path / "output.mp4",
        )
