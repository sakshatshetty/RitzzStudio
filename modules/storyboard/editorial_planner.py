from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

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


class EditorialTextPlanner(Protocol):
    def plan(
        self,
        contexts: Sequence[EditorialContext],
    ) -> dict[int, str]:
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

Use exactly one meaningful word.

Return JSON only:

{
  "callouts": [
    {
      "slot_id": 1,
      "text": "MYSTERY"
    }
  ]
}
""".strip()

    USER_PROMPT = """
Choose exactly ONE WORD for each supplied editorial position.

Look at:
- previous beat
- current beat
- next beat

Select the strongest memorable concept.

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
    ) -> dict[int, str]:
        if not contexts:
            return {}

        serialized_contexts = [
            {
                "slot_id": context.slot_id,
                "scene_index": context.scene_index,
                "previous": context.previous,
                "current": context.current,
                "next": context.next,
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

        raw_callouts = payload.get(
            "callouts",
            [],
        )

        if not isinstance(
            raw_callouts,
            list,
        ):
            return {}

        result: dict[int, str] = {}

        for item in raw_callouts:
            if not isinstance(
                item,
                dict,
            ):
                continue

            slot_id = item.get(
                "slot_id"
            )

            text = item.get(
                "text"
            )

            if not isinstance(
                slot_id,
                int,
            ):
                continue

            if not isinstance(
                text,
                str,
            ):
                continue

            cleaned = self._clean_text(
                text
            )

            if self._is_valid_callout(
                cleaned
            ):
                result[
                    slot_id
                ] = cleaned

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
        if not text:
            return False

        cleaned = cls._clean_text(
            text
        )

        words = cleaned.split()

        if len(words) != 1:
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

        if cleaned in banned:
            return False

        return True