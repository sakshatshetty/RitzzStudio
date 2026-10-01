import pytest

from scripts.run_render_stage import (
    _reject_semantic_qa_fail,
    _validate_production_render_format,
)


def test_production_render_format_requires_exact_resolution_fps_and_aspect_ratio():
    _validate_production_render_format(
        {"width": 1920, "height": 1080, "fps": 30.0}
    )


@pytest.mark.parametrize(
    ("probe", "message"),
    [
        ({"width": 1280, "height": 720, "fps": 30.0}, "1920x1080"),
        ({"width": 1920, "height": 1080, "fps": 29.97}, "30 FPS"),
        ({"width": 1920, "height": 1088, "fps": 30.0}, "1920x1080"),
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
