from pathlib import Path

import pytest

from modules.publishing.video_validation import validate_upload_master


def _probe(**updates):
    result = {
        "has_video": True,
        "has_audio": True,
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "video_codec_name": "h264",
        "video_bit_rate_bps": 10_000_000,
        "duration_seconds": 480.0,
        "audio_duration_seconds": 480.0,
        "audio_channels": 2,
    }
    result.update(updates)
    return result


def _validate(path: Path, probe: dict):
    return validate_upload_master(
        path,
        probe_media=lambda _path: probe,
        target_bitrate_bps=10_000_000,
    )


def test_upload_master_requires_exact_production_format(tmp_path):
    master = tmp_path / "ritzz_test.mp4"
    master.write_bytes(b"readable video")

    result = _validate(master, _probe())

    assert result["width"] == 1920
    assert result["height"] == 1080
    assert result["aspect_ratio"] == "16:9"
    assert result["fps"] == 30.0
    assert result["video_codec"] == "H.264"
    assert result["video_bitrate_bps"] == 10_000_000
    assert result["duration_seconds"] == 480.0
    assert result["audio_channels"] == 2
    assert result["file_size_bytes"] == len(b"readable video")


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"width": 640, "height": 360}, "1920x1080"),
        ({"width": 1280, "height": 720}, "1920x1080"),
        ({"fps": 29.97}, "30 FPS"),
        ({"video_codec_name": "hevc"}, "H.264"),
        ({"video_bit_rate_bps": 7_999_999}, "bitrate"),
        ({"video_bit_rate_bps": 12_000_001}, "bitrate"),
        ({"has_audio": False}, "valid video and audio"),
        ({"audio_duration_seconds": 0}, "duration or audio"),
        ({"duration_seconds": 0}, "duration or audio"),
        ({"audio_channels": 0}, "duration or audio"),
    ],
)
def test_upload_master_rejects_invalid_stream_properties(
    tmp_path,
    updates,
    message,
):
    master = tmp_path / "preview_360p.mp4"
    master.write_bytes(b"video")

    with pytest.raises(ValueError, match=message):
        _validate(master, _probe(**updates))


def test_upload_master_requires_readable_nonempty_file(tmp_path):
    missing = tmp_path / "missing.mp4"
    with pytest.raises(FileNotFoundError, match="missing or empty"):
        _validate(missing, _probe())

    empty = tmp_path / "empty.mp4"
    empty.touch()
    with pytest.raises(FileNotFoundError, match="missing or empty"):
        _validate(empty, _probe())


def test_upload_master_rejects_out_of_range_configured_bitrate(tmp_path):
    master = tmp_path / "ritzz_test.mp4"
    master.write_bytes(b"video")

    with pytest.raises(ValueError, match="between 8 and 12 Mbps"):
        validate_upload_master(
            master,
            probe_media=lambda _path: _probe(),
            target_bitrate_bps=7_000_000,
        )
