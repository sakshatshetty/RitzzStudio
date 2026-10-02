import pytest

from scripts.run_render_stage import (
    _reject_semantic_qa_fail,
    _reuse_or_create_thumbnail,
    _validate_production_render_format,
)


def test_production_render_format_requires_exact_resolution_fps_and_aspect_ratio():
    _validate_production_render_format(
        {
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "video_codec_name": "h264",
            "video_bit_rate_bps": 10_000_000,
        }
    )


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        ({"width": 1280, "height": 720, "fps": 30.0}, "1920x1080"),
        ({"width": 1920, "height": 1080, "fps": 29.97}, "30 FPS"),
        ({"width": 1920, "height": 1088, "fps": 30.0}, "1920x1080"),
        (
            {
                "width": 1920,
                "height": 1080,
                "fps": 30.0,
                "video_codec_name": "hevc",
                "video_bit_rate_bps": 10_000_000,
            },
            "H.264",
        ),
        (
            {
                "width": 1920,
                "height": 1080,
                "fps": 30.0,
                "video_codec_name": "h264",
                "video_bit_rate_bps": 1_150_000,
            },
            "bitrate",
        ),
    ],
)
def test_production_render_format_rejects_nonstandard_output(probe, message):
    with pytest.raises(RuntimeError, match=message):
        _validate_production_render_format(probe)


def test_semantic_qa_fail_blocks_but_review_is_allowed_for_human_review():
    with pytest.raises(RuntimeError, match="semantic QA found a clear"):
        _reject_semantic_qa_fail("FAIL")

    _reject_semantic_qa_fail("REVIEW")
    _reject_semantic_qa_fail("PASS")


def test_existing_thumbnail_is_reused_without_regeneration(tmp_path, monkeypatch):
    thumbnail = tmp_path / "thumbnail.jpg"
    thumbnail.write_bytes(b"existing")
    monkeypatch.setattr(
        "scripts.run_render_stage.create_thumbnail",
        lambda *_args, **_kwargs: pytest.fail("Existing thumbnail must be reused."),
    )

    result = _reuse_or_create_thumbnail(
        thumbnail,
        tmp_path / "scene.png",
        "Title",
        probe_media=lambda _path: {"width": 1280, "height": 720},
    )

    assert result == thumbnail
    assert thumbnail.read_bytes() == b"existing"


def test_invalid_existing_thumbnail_is_not_silently_replaced(tmp_path, monkeypatch):
    thumbnail = tmp_path / "thumbnail.jpg"
    thumbnail.write_bytes(b"existing")
    monkeypatch.setattr(
        "scripts.run_render_stage.create_thumbnail",
        lambda *_args, **_kwargs: pytest.fail("Invalid thumbnail must not be overwritten."),
    )

    with pytest.raises(RuntimeError, match="must remain 1280x720"):
        _reuse_or_create_thumbnail(
            thumbnail,
            tmp_path / "scene.png",
            "Title",
            probe_media=lambda _path: {"width": 640, "height": 360},
        )
