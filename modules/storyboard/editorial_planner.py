from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


def _load_project_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    if ENV_FILE.exists():
        load_dotenv(
            dotenv_path=ENV_FILE,
            override=False,
        )
    else:
        load_dotenv(
            override=False,
        )


_load_project_env()


@dataclass(frozen=True)
class EditorialContext:
    slot_id: int
    scene_index: int
    previous: str
    current: str
    next: str
    visual_description: str = ""
    props: tuple[str, ...] = ()
    character_action: str = ""
    background: str = ""


@dataclass(frozen=True)
class EditorialDecision:
    text: str = ""
    callout_not_warranted: bool = False
    reason: str | None = None
    position: str | None = None


class EditorialTextPlanner(Protocol):
    def plan(
        self,
        contexts: Sequence[EditorialContext],
    ) -> dict[int, EditorialDecision]:
        ...


class OpenAIEditorialTextPlanner:
    """
    Generate one-word editorial callouts for RITZZ.
    """

    DEFAULT_MODEL = "gpt-5.4-mini"

    SYSTEM_PROMPT = """
You create editorial callouts for animated RITZZ YouTube explainer videos.

IMPORTANT:
Every callout MUST be exactly ONE WORD.

The word should identify the strongest memorable idea in the surrounding
story beat.

This is EDITORIAL TEXT embedded inside the illustration.
It is NOT a subtitle.
It is NOT narration transcription.

RULES:

1. Exactly ONE WORD.
2. UPPERCASE.
3. Maximum 20 characters.
4. Use natural English.
5. The word must be strongly connected to the surrounding context.
6. Prefer a memorable concept over a narration fragment.
7. Do not copy a narration sentence.
8. Do not invent facts.
9. Do not exaggerate.
10. Do not turn uncertainty into certainty.
11. Avoid vague words such as:
    THIS
    THAT
    SOMETHING
    THING
    WHY
    HOW
    WHAT
12. Avoid awkward or malformed wording.
13. Do not use punctuation.
14. Do not use multiple words.
15. Do not use hyphenated phrases.
16. Do not use subtitles.
17. Do not simply repeat the current narration.

Good examples:

MYSTERY
MYTH
HISTORY
EVIDENCE
THEORY
SYMBOL
COSTUME
DANGER
SURVIVAL
STEREOTYPE
CULTURE
REALITY
CLUE
VISION
ADAPTATION
BELIEF
PROOF
SHADOW
LEGEND

Bad examples:

WHY
HOW
THIS
THAT
NOT
ONE REASON
REAL REASON
THE MYTH
NOT HISTORICAL
BELIEVABLE ISN T PROOF
THE PIRATE SYMBOL

Review every grouped scene. Choose a callout only when it emphasizes an
important idea, object, action, discovery, contrast, or reveal in that scene.
Target approximately one meaningful callout every 3–4 scenes across the video;
this is a pacing target, not a timer. Do not force weak or repetitive text.
For every scene, return either one callout or callout_not_warranted=true with
a concrete reason. Keep callouts at least 3 scenes apart when context supports
it. Longer gaps are acceptable when no scene warrants a word.
For each selected callout, choose one safe-zone position from top_left,
top_center, top_right, middle_left, middle_center, middle_right, lower_left,
lower_center, lower_right. Treat this position as a clear plane reserved for
the word, not as permission to draw over scene content. Use the visual
description, character action, props, and background to place it in likely
negative space away from the main character, face, action, and important
objects. Never place text over or through them. Do not cycle positions; choose
each scene independently. If no safe area is apparent, choose the least
obstructive zone and flag it for review so image QA can request a new
composition.

Return JSON only:

{
  "decisions": [
    {
      "scene_index": 1,
      "text": "",
      "callout_not_warranted": true,
      "reason": "The scene is transitional and has no distinct editorial idea.",
      "position": null
    }
  ]
}
""".strip()

    USER_PROMPT = """
Review every audio-timed scene and return exactly one decision for each.

Look at:
- previous beat
- current beat
- next beat

Choose a callout only when it is an important editorial emphasis for the
current visual segment. Otherwise mark the scene not warranted and explain why.

The result must be:
- exactly one word
- uppercase
- natural English
- contextual
- memorable
- editorial
- not a subtitle
- not narration transcription
- not a multi-word phrase
- or explicitly mark the scene not warranted, with a concrete reason
- for a callout, select one allowed position using composition and negative
  space; reserve it as clear empty space rather than placing text over content;
  do not use a mechanical rotation

Contexts:

{contexts}
""".strip()

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        _load_project_env()

        self.api_key = (
            api_key
            or os.getenv("OPENAI_API_KEY")
        )

        if not self.api_key:
            raise ValueError(
                "OPENAI_API_KEY is not configured. "
                f"Expected it in the project environment or {ENV_FILE}."
            )

        self.model = (
            model
            or os.getenv(
                "RITZZ_EDITORIAL_MODEL",
                self.DEFAULT_MODEL,
            )
        )

        self.client = OpenAI(
            api_key=self.api_key
        )

    def plan(
        self,
        contexts: Sequence[EditorialContext],
    ) -> dict[int, EditorialDecision]:
        if not contexts:
            return {}

        serialized_contexts = [
            {
                "slot_id": context.slot_id,
                "scene_index": context.scene_index,
                "previous": context.previous,
                "current": context.current,
                "next": context.next,
                "visual_description": context.visual_description,
                "props": context.props,
                "character_action": context.character_action,
                "background": context.background,
            }
            for context in contexts
        ]

        prompt = self.USER_PROMPT.format(
            contexts=json.dumps(
                serialized_contexts,
                ensure_ascii=False,
                indent=2,
            )
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": self.SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            response_format={
                "type": "json_object"
            },
        )

        content = (
            response.choices[0]
            .message
            .content
        )

        if not content:
            return {}

        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return {}

        raw_decisions = payload.get(
            "decisions",
            [],
        )

        if not isinstance(
            raw_decisions,
            list,
        ):
            return {}

        result: dict[int, EditorialDecision] = {}

        for item in raw_decisions:
            if not isinstance(
                item,
                dict,
            ):
                continue

            scene_index = item.get(
                "scene_index"
            )

            text = item.get(
                "text"
            )

            if not isinstance(scene_index, int) or isinstance(scene_index, bool):
                continue

            if not isinstance(text, str):
                continue

            not_warranted = item.get("callout_not_warranted")
            reason = item.get("reason")
            position = item.get("position")
            if not isinstance(not_warranted, bool):
                continue
            if reason is not None and not isinstance(reason, str):
                continue
            allowed_positions = {
                "top_left",
                "top_center",
                "top_right",
                "middle_left",
                "middle_center",
                "middle_right",
                "lower_left",
                "lower_center",
                "lower_right",
            }
            if position is not None and (
                not isinstance(position, str) or position not in allowed_positions
            ):
                continue

            cleaned = text.strip()
            if cleaned:
                result[scene_index] = EditorialDecision(
                    text=cleaned,
                    callout_not_warranted=not_warranted,
                    reason=(
                        reason.strip()
                        if not_warranted and isinstance(reason, str)
                        else None
                    ),
                    position=position,
                )
                continue

            if (
                not_warranted
                and isinstance(reason, str)
                and reason.strip()
            ):
                result[scene_index] = EditorialDecision(
                    callout_not_warranted=True,
                    reason=reason.strip(),
                )

        return result

    @staticmethod
    def _clean_text(
        text: str,
    ) -> str:
        cleaned = text.strip().upper()

        cleaned = re.sub(
            r"[^A-Z0-9\s]",
            " ",
            cleaned,
        )

        cleaned = re.sub(
            r"\s+",
            " ",
            cleaned,
        ).strip()

        return cleaned

    @classmethod
    def _is_valid_callout(
        cls,
        text: str,
    ) -> bool:
        if not text or len(text) > 20:
            return False

        cleaned = cls._clean_text(
            text
        )

        words = cleaned.split()

        if (
            len(words) != 1
            or cleaned != text
            or not re.fullmatch(r"[A-Z0-9]+", cleaned)
            or not any(character.isalpha() for character in cleaned)
        ):
            return False

        if len(cleaned) > 20:
            return False

        banned = {
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

        return cleaned not in banned