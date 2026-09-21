import math
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from modules.video.models import (
    VideoAssemblyPlan,
    VideoClip,
)

from modules.video.motion_models import (
    MotionInstruction,
    VideoMotionPlan,
)

from modules.video.render_engine import (
    FFmpegVideoRenderer,
)

from modules.video.render_models import (
    VideoRenderRequest,
    VideoRenderResult,
)


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
) -> Path:
    """
    Create a valid silent WAV file for rendering tests.
    """

    output_file = (
        tmp_path
        / "narration.wav"
    )

    sample_rate = 48_000

    frame_count = int(
        sample_rate
        * duration_seconds
    )

    with wave.open(
        str(output_file),
        "wb",
    ) as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(
            sample_rate
        )
        audio.writeframes(
            b"\x00\x00"
            * frame_count
        )

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


def test_render_three_scene_video(
    tmp_path: Path,
) -> None:
    images = create_test_images(
        tmp_path
    )

    audio = create_test_audio(
        tmp_path,
        duration_seconds=3.0,
    )

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