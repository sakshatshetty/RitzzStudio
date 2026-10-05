from modules.storyboard.editorial_qa import review_editorial_callouts
from modules.storyboard.models import StoryboardScene


def make_scene(
    index: int,
    *,
    callout: str = "",
    skipped: bool = True,
    reason: str | None = "No distinct editorial beat in this segment.",
) -> StoryboardScene:
    return StoryboardScene(
        scene_id=f"scene_{index:03}",
        section_id="s1",
        start_seconds=float(index - 1),
        duration_seconds=1,
        narration=f"Grouped visual beat number {index}.",
        visual_description=f"A simple illustration of beat number {index}.",
        image_prompt="Simple 2D cartoon scene.",
        text_overlay=callout,
        callout_not_warranted=skipped,
        callout_not_warranted_reason=reason,
        callout_position="top_left" if callout else None,
    )


def test_valid_one_word_uppercase_callout_is_counted():
    result = review_editorial_callouts(
        [make_scene(1, callout="EVIDENCE", skipped=False, reason=None)]
    )

    assert result.status == "PASS"
    assert result.scene_statuses["scene_001"] == "callout_present_valid"
    assert result.callouts_present == 1
    assert result.intentionally_skipped_callouts == 0


def test_malformed_callout_is_not_treated_as_present():
    result = review_editorial_callouts(
        [make_scene(1, callout="TWO WORDS", skipped=False, reason=None)]
    )

    assert result.status == "REVIEW"
    assert result.scene_statuses["scene_001"] == "malformed_callout"
    assert result.callouts_present == 1
    assert result.malformed_callouts == 1


def test_intentional_no_callout_requires_and_counts_reason():
    result = review_editorial_callouts([make_scene(1)])

    assert result.status == "PASS"
    assert result.scene_statuses["scene_001"] == "intentionally_not_warranted"
    assert result.intentionally_skipped_callouts == 1
    assert result.unexpected_missing_callouts == 0


def test_missing_callout_without_explicit_reason_is_reviewed():
    result = review_editorial_callouts(
        [make_scene(1, skipped=False, reason=None)]
    )

    assert result.status == "REVIEW"
    assert result.scene_statuses["scene_001"] == "missing_unexpectedly"
    assert result.unexpected_missing_callouts == 1
    assert result.findings


def test_target_spacing_reports_average_and_longest_gap():
    scenes = [
        make_scene(index, callout=word, skipped=False, reason=None)
        if index in {3, 6, 10}
        else make_scene(index)
        for index, word in ((i, "EVIDENCE") for i in range(1, 11))
    ]

    result = review_editorial_callouts(scenes)

    assert result.total_scenes == 10
    assert result.callouts_present == 3
    assert result.intentionally_skipped_callouts == 7
    assert result.average_scenes_between_callouts == 3.5
    assert result.longest_gap_between_callouts == 4


def test_overfrequent_callouts_are_flagged_for_review():
    result = review_editorial_callouts(
        [
            make_scene(1, callout="EVIDENCE", skipped=False, reason=None),
            make_scene(2, callout="MYSTERY", skipped=False, reason=None),
        ]
    )

    assert result.status == "REVIEW"
    assert any("more frequent" in finding for finding in result.findings)


def test_long_callout_gap_is_flagged_for_review():
    scenes = [
        make_scene(index, callout="EVIDENCE", skipped=False, reason=None)
        if index in {1, 7}
        else make_scene(index)
        for index in range(1, 9)
    ]

    result = review_editorial_callouts(scenes)

    assert result.longest_gap_between_callouts == 6
    assert result.status == "REVIEW"
    assert any("gaps exceed" in finding for finding in result.findings)


def test_callout_requires_contextual_position():
    scene = make_scene(1, callout="EVIDENCE", skipped=False, reason=None)
    scene.callout_position = None

    result = review_editorial_callouts([scene])

    assert result.status == "REVIEW"
    assert result.malformed_callouts == 1
