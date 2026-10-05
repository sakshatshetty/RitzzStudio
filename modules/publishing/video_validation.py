from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

MIN_VIDEO_BITRATE_BPS = 8_000_000
MAX_VIDEO_BITRATE_BPS = 12_000_000
VIDEO_BITRATE_TOLERANCE = 0.20


def validate_upload_master(
    video_file: str | Path,
    *,
    probe_media: Callable[[str | Path], dict[str, Any]],
    target_bitrate_bps: int,
) -> dict[str, Any]:
    path = Path(video_file)
    if not path.is_file() or path.stat().st_size == 0:
        raise FileNotFoundError(f"Upload master is missing or empty: {path}")
    if not MIN_VIDEO_BITRATE_BPS <= target_bitrate_bps <= MAX_VIDEO_BITRATE_BPS:
        raise ValueError(
            "Configured production video bitrate must be between 8 and 12 Mbps; "
            f"received {target_bitrate_bps} bps."
        )

    probe = probe_media(path)
    width = probe.get("width")
    height = probe.get("height")
    if width != 1920 or height != 1080 or width * 9 != height * 16:
        raise ValueError(
            "YouTube upload requires the 1920x1080 16:9 production master; "
            f"received {width}x{height}."
        )

    fps = probe.get("fps")
    if (
        not isinstance(fps, (int, float))
        or isinstance(fps, bool)
        or not math.isclose(fps, 30.0, rel_tol=0.0, abs_tol=0.01)
    ):
        raise ValueError(f"YouTube upload requires 30 FPS; received {fps}.")
    if probe.get("video_codec_name") != "h264":
        raise ValueError(
            "YouTube upload requires H.264 video; received "
            f"{probe.get('video_codec_name')}."
        )
    if not probe.get("has_video") or not probe.get("has_audio"):
        raise ValueError("YouTube upload master must contain valid video and audio streams.")

    duration = probe.get("duration_seconds")
    audio_duration = probe.get("audio_duration_seconds")
    audio_channels = probe.get("audio_channels")
    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or not math.isfinite(duration)
        or duration <= 0
        or not isinstance(audio_duration, (int, float))
        or isinstance(audio_duration, bool)
        or not math.isfinite(audio_duration)
        or audio_duration <= 0
        or not isinstance(audio_channels, int)
        or isinstance(audio_channels, bool)
        or audio_channels < 1
    ):
        raise ValueError(
            "YouTube upload master has an invalid duration or audio stream."
        )

    bitrate = probe.get("video_bit_rate_bps")
    minimum_bitrate = max(
        MIN_VIDEO_BITRATE_BPS,
        int(target_bitrate_bps * (1 - VIDEO_BITRATE_TOLERANCE)),
    )
    maximum_bitrate = min(
        MAX_VIDEO_BITRATE_BPS,
        int(target_bitrate_bps * (1 + VIDEO_BITRATE_TOLERANCE)),
    )
    if (
        not isinstance(bitrate, int)
        or isinstance(bitrate, bool)
        or not minimum_bitrate <= bitrate <= maximum_bitrate
    ):
        raise ValueError(
            "Upload master video bitrate must be within "
            f"{minimum_bitrate}-{maximum_bitrate} bps for the configured target; "
            f"received {bitrate}."
        )

    return {
        "width": width,
        "height": height,
        "aspect_ratio": "16:9",
        "fps": fps,
        "video_codec": "H.264",
        "video_bitrate_bps": bitrate,
        "duration_seconds": duration,
        "audio_duration_seconds": audio_duration,
        "audio_channels": audio_channels,
        "file_size_bytes": path.stat().st_size,
    }
