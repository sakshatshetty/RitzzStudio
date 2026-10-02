from __future__ import annotations

import re
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel

from modules.storyboard.models import StoryboardScene


EditorialCalloutStatus = Literal["PASS", "REVIEW"]


class EditorialCalloutQAResult(BaseModel):
    status: EditorialCalloutStatus
    scene_statuses: dict[str, str]
    total_scenes: int
    callouts_present: int
    intentionally_skipped_callouts: int
    unexpected_missing_callouts: int
    malformed_callouts: int
    average_scenes_between_callouts: float | None
    longest_gap_between_callouts: int | None
    findings: list[str]

    def metrics(self) -> dict[str, int | float | None]:
        return {
            "total_scenes": self.total_scenes,
            "callouts_present": self.callouts_present,
            "intentionally_skipped_callouts": self.intentionally_skipped_callouts,
            "unexpected_missing_callouts": self.unexpected_missing_callouts,
            "malformed_callouts": self.malformed_callouts,
            "average_scenes_between_callouts": self.average_scenes_between_callouts,
            "longest_gap_between_callouts": self.longest_gap_between_callouts,
        }


_VALID_CALLOUT = re.compile(r"^[A-Z0-9]+$")
_BANNED_CALLOUTS = {
    "WHY",
    "HOW",
    "WHAT",
    "WHEN",
    "WHERE",
    "THIS",
    "THAT",
    "SOMETHING",
    "THING",
    "NOT",
    "ONLY",
    "REASON",
}


def review_editorial_callouts(
    scenes: list[StoryboardScene],
) -> EditorialCalloutQAResult:
    """Classify each scene's callout decision and summarize video coverage."""
    statuses: dict[str, str] = {}
    findings: list[str] = []
    callout_positions: list[int] = []
    present = 0
    skipped = 0
    unexpected = 0
    malformed = 0

    for index, scene in enumerate(scenes):
        text = scene.text_overlay
        skip_reason = (scene.callout_not_warranted_reason or "").strip()
        if text:
            present += 1
            if (
                scene.callout_not_warranted
                or skip_reason
                or text != text.strip()
                or not _is_valid_callout(text)
            ):
                statuses[scene.scene_id] = "malformed_callout"
                malformed += 1
                findings.append(
                    f"{scene.scene_id}: callout must be one valid uppercase "
                    "editorial word with no conflicting skip decision."
                )
            else:
                statuses[scene.scene_id] = "callout_present_valid"
                callout_positions.append(index)
        elif scene.callout_not_warranted and skip_reason:
            statuses[scene.scene_id] = "intentionally_not_warranted"
            skipped += 1
        else:
            statuses[scene.scene_id] = "missing_unexpectedly"
            unexpected += 1
            findings.append(
                f"{scene.scene_id}: callout is missing without an explicit "
                "not-warranted decision and reason."
            )

    gaps = [
        right - left
        for left, right in pairwise(callout_positions)
    ]
    average_gap = sum(gaps) / len(gaps) if gaps else None
    longest_gap = max(gaps) if gaps else None
    if gaps and min(gaps) < 3:
        findings.append(
            "Editorial callouts are more frequent than the 3-scene minimum "
            "target interval."
        )

    return EditorialCalloutQAResult(
        status="REVIEW" if unexpected or malformed or (gaps and min(gaps) < 3) else "PASS",
        scene_statuses=statuses,
        total_scenes=len(scenes),
        callouts_present=present,
        intentionally_skipped_callouts=skipped,
        unexpected_missing_callouts=unexpected,
        malformed_callouts=malformed,
        average_scenes_between_callouts=average_gap,
        longest_gap_between_callouts=longest_gap,
        findings=findings,
    )


def _is_valid_callout(text: str) -> bool:
    return (
        len(text) <= 20
        and _VALID_CALLOUT.fullmatch(text) is not None
        and any(character.isalpha() for character in text)
        and text not in _BANNED_CALLOUTS
    )
