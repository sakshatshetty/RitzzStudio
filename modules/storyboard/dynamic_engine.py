from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from modules.image.prompt_builder import ImagePromptBuilder
from modules.storyboard.editorial_planner import (
    EditorialContext,
    EditorialTextPlanner,
)
from modules.storyboard.models import Storyboard, StoryboardScene


@dataclass(frozen=True)
class _VisualBeat:
    source_scene: StoryboardScene
    beat: str
    duration_seconds: float


class DynamicStoryboardEngine:
    """
    Dynamic RITZZ storyboard engine.

    Production rules:
    - 1–3 second scenes.
    - Dynamic pacing.
    - Static camera.
    - Hard cuts.
    - Editorial callout every 3–4 scenes.
    - Exactly one word for production editorial text.
    - Exact target duration.
    """

    WORDS_PER_SECOND = 2.4

    MIN_SCENE_DURATION = 1.0
    MAX_SCENE_DURATION = 3.0

    MAX_WORDS_PER_BEAT = 7
    MIN_WORDS_PER_BEAT = 2

    DEFAULT_TARGET_SCENE_DURATION = 2.0

    MIN_EDITORIAL_GAP_SCENES = 3
    MAX_EDITORIAL_GAP_SCENES = 4

    # Production editorial limits.
    PRODUCTION_EDITORIAL_MAX_WORDS = 1
    PRODUCTION_EDITORIAL_MAX_CHARACTERS = 20

    HIGH_VALUE_PHRASES = (
        ("the real reason", "REASON"),
        ("real reason", "REASON"),
        ("the mystery", "MYSTERY"),
        ("the secret", "SECRET"),
        ("the truth", "TRUTH"),
        ("most realistic", "REALITY"),
        ("surprising", "SURPRISE"),
        ("surprise", "SURPRISE"),
        ("actually", "REALITY"),
        ("important", "CLUE"),
        ("historical sources", "HISTORY"),
        ("historical evidence", "EVIDENCE"),
        ("well documented", "EVIDENCE"),
        ("myth spread", "MYTH"),
        ("myth", "MYTH"),
        ("before", "BEFORE"),
        ("after", "AFTER"),
        ("pirate culture", "CULTURE"),
        ("life aboard", "SEA"),
        ("life at sea", "SEA"),
        ("lost an eye", "VISION"),
        ("eye patch", "SYMBOL"),
        ("eye patches", "SYMBOL"),
        ("adaptation", "ADAPTATION"),
        ("stereotype", "STEREOTYPE"),
        ("practical", "SURVIVAL"),
        ("evidence", "EVIDENCE"),
        ("belief", "BELIEF"),
        ("dangerous", "DANGER"),
        ("danger", "DANGER"),
        ("injury", "INJURY"),
        ("costume", "COSTUME"),
        ("symbol", "SYMBOL"),
        ("popular culture", "CULTURE"),
        ("pop culture", "CULTURE"),
        ("fiction", "FICTION"),
        ("hollywood", "HOLLYWOOD"),
        ("history", "HISTORY"),
        ("theory", "THEORY"),
        ("proof", "PROOF"),
        ("common assumption", "ASSUMPTION"),
    )

    HIGH_VALUE_WORDS = {
        "mystery",
        "secret",
        "truth",
        "myth",
        "evidence",
        "history",
        "historical",
        "pirate",
        "pirates",
        "ship",
        "ships",
        "sea",
        "battle",
        "danger",
        "dangerous",
        "injury",
        "lost",
        "eye",
        "patch",
        "adaptation",
        "belief",
        "stereotype",
        "culture",
        "practical",
        "reason",
        "surprising",
        "surprise",
        "costume",
        "symbol",
        "theory",
        "proof",
        "fiction",
        "hollywood",
        "assumption",
        "vision",
        "survival",
        "legend",
        "clue",
    }

    STOP_WORDS = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "so",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "from",
        "by",
        "is",
        "was",
        "were",
        "are",
        "be",
        "been",
        "that",
        "this",
        "these",
        "those",
        "it",
        "they",
        "he",
        "she",
        "we",
        "you",
        "i",
        "as",
        "at",
        "into",
        "their",
        "his",
        "her",
        "our",
        "your",
        "have",
        "has",
        "had",
        "did",
        "do",
        "does",
        "not",
        "than",
        "then",
        "also",
        "just",
        "about",
        "because",
        "while",
        "when",
        "what",
        "why",
        "how",
    }

    BANNED_PRODUCTION_EDITORIAL = {
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

    BANNED_LEGACY_EDITORIAL = {
        "WHY",
        "HOW",
        "WHAT",
        "WHEN",
        "WHERE",
        "THIS",
        "THAT",
        "SOMETHING",
        "THE THING",
        "ONE REASON ONLY",
        "THE ONLY REASON",
        "NOT NEVER",
    }

    OBVIOUS_BAD_FRAGMENTS = {
        "PART LARGER PIRATE",
        "EYE LOST EYE",
        "PIRATE SHIP WORN",
        "SPECIFIC REASON ENTIRE PIRATE",
        "BECOMES FAMILIAR ENOUGH",
    }

    def __init__(
        self,
        target_scene_duration_seconds: float = DEFAULT_TARGET_SCENE_DURATION,
        editorial_planner: EditorialTextPlanner | None = None,
        prompt_builder: ImagePromptBuilder | None = None,
    ) -> None:
        if target_scene_duration_seconds <= 0:
            raise ValueError(
                "target_scene_duration_seconds must be greater than zero."
            )

        self.target_scene_duration_seconds = (
            target_scene_duration_seconds
        )

        self.editorial_planner = editorial_planner

        self.prompt_builder = (
            prompt_builder
            or ImagePromptBuilder()
        )

    # ======================================================================
    # PUBLIC
    # ======================================================================

    def create_pilot_storyboard(
        self,
        source_storyboard: Storyboard,
        target_duration_seconds: float = 180.0,
    ) -> Storyboard:
        if target_duration_seconds <= 0:
            raise ValueError(
                "target_duration_seconds must be greater than zero."
            )

        if not source_storyboard.scenes:
            raise ValueError(
                "Storyboard has no scenes."
            )

        beats = self._build_visual_beats(
            source_storyboard
        )

        if not beats:
            raise ValueError(
                "No visual beats could be created from the source storyboard."
            )

        selected_beats: list[_VisualBeat] = []
        accumulated_duration = 0.0

        for beat in beats:
            if (
                accumulated_duration
                >= target_duration_seconds
            ):
                break

            selected_beats.append(
                beat
            )

            accumulated_duration += (
                beat.duration_seconds
            )

        if not selected_beats:
            raise ValueError(
                "No beats were selected for the pilot storyboard."
            )

        scenes = self._build_dynamic_scenes(
            selected_beats,
            topic=source_storyboard.topic,
        )

        scenes = self._apply_editorial_callouts(
            scenes
        )

        scenes = self._fit_total_duration(
            scenes,
            target_duration_seconds,
        )

        scenes = self._rebuild_prompts(
            scenes,
            topic=source_storyboard.topic,
        )

        self._validate_dynamic_scenes(
            scenes,
            target_duration_seconds,
        )

        final_duration = sum(
            scene.duration_seconds
            for scene in scenes
        )

        return Storyboard(
            topic=source_storyboard.topic,
            target_duration_seconds=int(
                target_duration_seconds
            ),
            scenes=scenes,
            total_scene_duration_seconds=final_duration,
            target_scene_duration_seconds=(
                self.target_scene_duration_seconds
            ),
        )

    def create_storyboard(
        self,
        source_storyboard: Storyboard,
        target_duration_seconds: float | None = None,
    ) -> Storyboard:
        target = (
            target_duration_seconds
            if target_duration_seconds is not None
            else float(
                source_storyboard.target_duration_seconds
            )
        )

        return self.create_pilot_storyboard(
            source_storyboard,
            target_duration_seconds=target,
        )

    @staticmethod
    def save_storyboard(
        storyboard: Storyboard,
        output_file: str | Path,
    ) -> Path:
        output_path = Path(
            output_file
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path.write_text(
            storyboard.model_dump_json(
                indent=2
            ),
            encoding="utf-8",
        )

        return output_path

    @staticmethod
    def load_storyboard(
        storyboard_file: str | Path,
    ) -> Storyboard:
        path = Path(
            storyboard_file
        )

        if not path.exists():
            raise FileNotFoundError(
                f"Storyboard file not found: {path}"
            )

        return Storyboard.model_validate_json(
            path.read_text(
                encoding="utf-8"
            )
        )

    # ======================================================================
    # NORMALIZATION
    # ======================================================================

    @staticmethod
    def _normalize_text(
        text: str,
    ) -> str:
        return re.sub(
            r"\s+",
            " ",
            text.strip(),
        )

    @staticmethod
    def _word_count(
        text: str,
    ) -> int:
        return len(
            [
                word
                for word in text.split()
                if word.strip()
            ]
        )

    # ======================================================================
    # EDITORIAL SCORE
    # ======================================================================

    def _editorial_score(
        self,
        text: str,
    ) -> int:
        if not isinstance(text, str):
            return 0

        cleaned = self._normalize_text(
            text
        )

        if not cleaned:
            return 0

        lowered = cleaned.lower()

        score = 0

        for phrase, _replacement in (
            self.HIGH_VALUE_PHRASES
        ):
            if phrase in lowered:
                score += 10

        words = {
            word.lower().strip(
                ".,!?;:()[]{}"
            )
            for word in cleaned.split()
        }

        for word in words:
            if word in self.HIGH_VALUE_WORDS:
                score += 3

        if re.search(
            r"\b\d[\d,]*\b",
            cleaned,
        ):
            score += 4

        if cleaned.endswith("?"):
            score -= 4

        generic_words = {
            "this",
            "that",
            "it",
            "thing",
            "something",
            "people",
            "someone",
        }

        for word in words:
            if word in generic_words:
                score -= 1

        word_count = self._word_count(
            cleaned
        )

        if word_count > 4:
            score -= min(
                10,
                word_count - 4,
            )

        return score

    # ======================================================================
    # VISUAL BEATS
    # ======================================================================

    def _build_visual_beats(
        self,
        storyboard: Storyboard,
    ) -> list[_VisualBeat]:
        beats: list[_VisualBeat] = []

        for source_scene in storyboard.scenes:
            narration = (
                source_scene.narration.strip()
            )

            if not narration:
                continue

            chunks = (
                self._split_narration_into_beats(
                    narration
                )
            )

            for chunk in chunks:
                beats.append(
                    _VisualBeat(
                        source_scene=source_scene,
                        beat=chunk,
                        duration_seconds=(
                            self._estimate_duration(
                                chunk
                            )
                        ),
                    )
                )

        return beats

    def _split_narration_into_beats(
        self,
        narration: str,
    ) -> list[str]:
        cleaned = self._normalize_text(
            narration
        )

        if not cleaned:
            return []

        sentences = re.split(
            r"(?<=[.!?])\s+",
            cleaned,
        )

        beats: list[str] = []

        for sentence in sentences:
            sentence = sentence.strip()

            if not sentence:
                continue

            words = sentence.split()

            if len(words) <= self.MAX_WORDS_PER_BEAT:
                beats.append(sentence)
                continue

            current_words: list[str] = []

            for word in words:
                current_words.append(
                    word
                )

                if (
                    len(current_words)
                    >= self.MAX_WORDS_PER_BEAT
                ):
                    beats.append(
                        " ".join(
                            current_words
                        )
                    )

                    current_words = []

            if current_words:
                trailing = " ".join(
                    current_words
                )

                if (
                    self._word_count(
                        trailing
                    )
                    < self.MIN_WORDS_PER_BEAT
                    and beats
                ):
                    beats[-1] = (
                        f"{beats[-1]} "
                        f"{trailing}"
                    )
                else:
                    beats.append(
                        trailing
                    )

        return self._merge_tiny_beats(
            beats
        )

    def _merge_tiny_beats(
        self,
        beats: list[str],
    ) -> list[str]:
        if len(beats) <= 1:
            return beats

        merged: list[str] = []

        index = 0

        while index < len(beats):
            current = beats[index]

            if (
                self._word_count(
                    current
                )
                < self.MIN_WORDS_PER_BEAT
                and index + 1 < len(beats)
            ):
                next_text = beats[
                    index + 1
                ]

                combined = (
                    f"{current} "
                    f"{next_text}"
                )

                if (
                    self._word_count(
                        combined
                    )
                    <= self.MAX_WORDS_PER_BEAT + 2
                ):
                    merged.append(
                        combined
                    )

                    index += 2
                    continue

            merged.append(
                current
            )

            index += 1

        return merged

    # ======================================================================
    # DURATION
    # ======================================================================

    def _estimate_duration(
        self,
        text: str,
    ) -> float:
        raw_duration = (
            self._word_count(text)
            / self.WORDS_PER_SECOND
        )

        return min(
            self.MAX_SCENE_DURATION,
            max(
                self.MIN_SCENE_DURATION,
                raw_duration,
            ),
        )

    # ======================================================================
    # SCENES
    # ======================================================================

    def _build_dynamic_scenes(
        self,
        beats: list[_VisualBeat],
        topic: str,
    ) -> list[StoryboardScene]:
        scenes: list[StoryboardScene] = []

        current_start = 0.0

        for index, visual_beat in enumerate(
            beats,
            start=1,
        ):
            source_scene = (
                visual_beat.source_scene
            )

            visual_description = (
                f"{source_scene.visual_description.strip()} "
                f"Focus specifically on this visual beat: "
                f"{visual_beat.beat}"
            )

            scenes.append(
                StoryboardScene(
                    scene_id=f"scene_{index:03d}",
                    section_id=source_scene.section_id,
                    start_seconds=current_start,
                    duration_seconds=(
                        visual_beat.duration_seconds
                    ),
                    narration=visual_beat.beat,
                    visual_style="stickman",
                    visual_description=(
                        visual_description
                    ),
                    character_action=(
                        source_scene.character_action
                    ),
                    background=(
                        source_scene.background
                    ),
                    props=list(
                        source_scene.props
                    ),
                    text_overlay="",
                    camera_motion="static",
                    transition="cut",
                    research_sources=list(
                        source_scene.research_sources
                    ),
                    image_prompt="placeholder",
                )
            )

            current_start += (
                visual_beat.duration_seconds
            )

        return self._rebuild_prompts(
            scenes,
            topic=topic,
        )

    # ======================================================================
    # EDITORIAL POSITION
    # ======================================================================

    def _build_editorial_slots(
        self,
        scene_count: int,
    ) -> list[int]:
        if scene_count < 4:
            return []

        positions: list[int] = []

        current_position = 3

        gap_pattern = [
            3,
            4,
            4,
            3,
            3,
            4,
            3,
            4,
        ]

        pattern_index = 0

        while current_position < scene_count:
            positions.append(
                current_position
            )

            current_position += gap_pattern[
                pattern_index
                % len(gap_pattern)
            ]

            pattern_index += 1

        return positions

    # ======================================================================
    # EDITORIAL PLANNING
    # ======================================================================

    def _apply_editorial_callouts(
        self,
        scenes: list[StoryboardScene],
    ) -> list[StoryboardScene]:
        if not scenes:
            return scenes

        editorial_indices = (
            self._build_editorial_slots(
                len(scenes)
            )
        )

        planned = (
            self._plan_editorial_callouts(
                scenes,
                editorial_indices,
            )
        )

        updated: list[StoryboardScene] = []

        editorial_index_set = set(
            editorial_indices
        )

        for index, scene in enumerate(
            scenes
        ):
            if index not in editorial_index_set:
                updated.append(
                    scene.model_copy(
                        update={
                            "text_overlay": ""
                        }
                    )
                )
                continue

            text = planned.get(
                index,
                "",
            )

            if not self._is_production_editorial_text(
                text
            ):
                text = (
                    self._build_production_editorial_text(
                        scenes,
                        index,
                    )
                )

            updated.append(
                scene.model_copy(
                    update={
                        "text_overlay": text
                    }
                )
            )

        return self._rebuild_prompts(
            updated
        )

    def _plan_editorial_callouts(
        self,
        scenes: list[StoryboardScene],
        ordered_indices: list[int],
    ) -> dict[int, str]:
        if not ordered_indices:
            return {}

        contexts: list[
            EditorialContext
        ] = []

        for slot_id, index in enumerate(
            ordered_indices,
            start=1,
        ):
            contexts.append(
                EditorialContext(
                    slot_id=slot_id,
                    scene_index=index + 1,
                    previous=(
                        scenes[index - 1].narration
                        if index > 0
                        else ""
                    ),
                    current=(
                        scenes[index].narration
                    ),
                    next=(
                        scenes[index + 1].narration
                        if index + 1 < len(scenes)
                        else ""
                    ),
                )
            )

        if self.editorial_planner is None:
            return {}

        try:
            planned = (
                self.editorial_planner.plan(
                    contexts
                )
            )
        except Exception:
            planned = {}

        result: dict[int, str] = {}

        for context in contexts:
            candidate = planned.get(
                context.slot_id,
                "",
            )

            cleaned = (
                self._clean_editorial_text(
                    candidate
                )
            )

            if self._is_production_editorial_text(
                cleaned
            ):
                result[
                    context.scene_index - 1
                ] = cleaned

        return result

    # ======================================================================
    # PRODUCTION ONE-WORD EDITORIAL
    # ======================================================================

    def _build_production_editorial_text(
        self,
        scenes: list[StoryboardScene],
        index: int,
    ) -> str:
        context_parts = [
            (
                scenes[index - 1].narration
                if index > 0
                else ""
            ),
            scenes[index].narration,
            (
                scenes[index + 1].narration
                if index + 1 < len(scenes)
                else ""
            ),
        ]

        context = " ".join(
            context_parts
        ).lower()

        # Strong contextual phrases first.
        for phrase, replacement in (
            self.HIGH_VALUE_PHRASES
        ):
            if phrase in context:
                if self._is_production_editorial_text(
                    replacement
                ):
                    return replacement

        # High-value single words.
        words = [
            word.lower().strip(
                ".,!?;:()[]{}"
            )
            for word in context.split()
        ]

        for word in words:
            if word in self.HIGH_VALUE_WORDS:
                candidate = word.upper()

                if self._is_production_editorial_text(
                    candidate
                ):
                    return candidate

        return "CLUE"

    # ======================================================================
    # LEGACY EDITORIAL API
    # ======================================================================

    def _build_editorial_text(
        self,
        scenes: (
            str
            | list[StoryboardScene]
            | StoryboardScene
        ),
        index: int = 0,
    ) -> str:
        """
        Legacy helper retained for existing tests.

        Production does NOT use this for final callouts.
        """

        if isinstance(
            scenes,
            str,
        ):
            return (
                self._build_editorial_text_from_text(
                    scenes
                )
            )

        if isinstance(
            scenes,
            StoryboardScene,
        ):
            scene_list = [
                scenes
            ]
            scene_index = 0

        else:
            scene_list = scenes
            scene_index = index

        if not scene_list:
            return ""

        if (
            scene_index < 0
            or scene_index >= len(scene_list)
        ):
            raise IndexError(
                "Editorial scene index is out of range."
            )

        return self._fallback_editorial_text(
            scene_list,
            scene_index,
        )

    def _build_editorial_text_from_text(
        self,
        text: str,
    ) -> str:
        """
        Legacy multi-word behavior retained so the existing test suite
        remains compatible.
        """

        cleaned = self._normalize_text(
            text
        )

        if not cleaned:
            return ""

        lowered = cleaned.lower()

        # Legacy phrase mappings.
        legacy_phrases = (
            ("the real reason", "THE REAL REASON"),
            ("real reason", "THE REAL REASON"),
            ("the mystery", "THE MYSTERY"),
            ("the secret", "THE SECRET"),
            ("the truth", "THE TRUTH"),
            ("historical sources", "HISTORICAL SOURCES"),
            ("historical evidence", "HISTORICAL EVIDENCE"),
            ("myth spread", "THE MYTH SPREAD"),
            ("myth", "THE MYTH"),
            ("before", "BEFORE"),
            ("after", "AFTER"),
        )

        for phrase, replacement in legacy_phrases:
            if phrase in lowered:
                return replacement

        # Preserve the older numeric behavior used by the tests.
        numeric_match = re.search(
            r"\b(\d[\d,]*)\s+([A-Za-z]+)",
            cleaned,
        )

        if numeric_match:
            number = (
                numeric_match.group(1)
            )

            word = (
                numeric_match.group(2)
            )

            return (
                f"{number} {word}"
            ).upper()

        words = [
            word.lower().strip(
                ".,!?;:()[]{}"
            )
            for word in cleaned.split()
        ]

        meaningful = [
            word
            for word in words
            if (
                word
                and word not in self.STOP_WORDS
                and len(word) > 3
            )
        ]

        candidates: list[
            tuple[int, str]
        ] = []

        for word in meaningful:
            if word in self.HIGH_VALUE_WORDS:
                candidate = (
                    f"THE {word.upper()}"
                )

                if self._is_valid_editorial_text(
                    candidate
                ):
                    candidates.append(
                        (
                            self._editorial_score(
                                word
                            ),
                            candidate,
                        )
                    )

        if candidates:
            candidates.sort(
                key=lambda item: item[0],
                reverse=True,
            )

            return candidates[0][1]

        return "THE BIG CLUE"

    def _fallback_editorial_text(
        self,
        scenes: list[StoryboardScene],
        index: int,
    ) -> str:
        context_parts = [
            (
                scenes[index - 1].narration
                if index > 0
                else ""
            ),
            scenes[index].narration,
            (
                scenes[index + 1].narration
                if index + 1 < len(scenes)
                else ""
            ),
        ]

        return self._build_editorial_text_from_text(
            " ".join(context_parts)
        )

    # ======================================================================
    # EDITORIAL VALIDATION
    # ======================================================================

    @staticmethod
    def _clean_editorial_text(
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

    def _is_production_editorial_text(
        self,
        text: str,
    ) -> bool:
        """
        Strict production validator.

        Exactly ONE word.
        """

        if not text:
            return False

        cleaned = (
            self._clean_editorial_text(
                text
            )
        )

        words = cleaned.split()

        if len(words) != 1:
            return False

        if (
            len(cleaned)
            > self.PRODUCTION_EDITORIAL_MAX_CHARACTERS
        ):
            return False

        if (
            cleaned
            in self.BANNED_PRODUCTION_EDITORIAL
        ):
            return False

        return True

    def _is_valid_editorial_text(
        self,
        text: str,
    ) -> bool:
        """
        Legacy validator retained for compatibility with existing tests.
        """

        if not text:
            return False

        cleaned = (
            self._clean_editorial_text(
                text
            )
        )

        words = cleaned.split()

        if not (
            1 <= len(words) <= 4
        ):
            return False

        if len(cleaned) > 50:
            return False

        if cleaned in self.BANNED_LEGACY_EDITORIAL:
            return False

        if cleaned in self.OBVIOUS_BAD_FRAGMENTS:
            return False

        if "NOT NEVER" in cleaned:
            return False

        return True

    # ======================================================================
    # EXACT DURATION
    # ======================================================================

    def _fit_total_duration(
        self,
        scenes: list[StoryboardScene],
        target_duration_seconds: float,
    ) -> list[StoryboardScene]:
        if not scenes:
            return scenes

        minimum_possible = (
            len(scenes)
            * self.MIN_SCENE_DURATION
        )

        maximum_possible = (
            len(scenes)
            * self.MAX_SCENE_DURATION
        )

        if target_duration_seconds < minimum_possible:
            raise ValueError(
                f"Target duration "
                f"{target_duration_seconds:.3f}s is too short "
                f"for {len(scenes)} scenes."
            )

        if target_duration_seconds > maximum_possible:
            raise ValueError(
                f"Target duration "
                f"{target_duration_seconds:.3f}s is too long "
                f"for {len(scenes)} scenes."
            )

        durations = [
            scene.duration_seconds
            for scene in scenes
        ]

        total = sum(durations)

        if abs(
            total
            - target_duration_seconds
        ) <= 0.000001:
            return self._rebuild_timeline(
                scenes
            )

        # --------------------------------------------------------------
        # ADD TIME
        # --------------------------------------------------------------

        if total < target_duration_seconds:
            remaining = (
                target_duration_seconds
                - total
            )

            while remaining > 0.000001:
                adjustable = [
                    i
                    for i, duration
                    in enumerate(durations)
                    if (
                        duration
                        < self.MAX_SCENE_DURATION
                        - 0.000001
                    )
                ]

                if not adjustable:
                    raise ValueError(
                        "Unable to increase storyboard duration."
                    )

                available_total = sum(
                    self.MAX_SCENE_DURATION
                    - durations[i]
                    for i in adjustable
                )

                change = min(
                    remaining,
                    available_total,
                )

                for i in adjustable:
                    available = (
                        self.MAX_SCENE_DURATION
                        - durations[i]
                    )

                    durations[i] += (
                        change
                        * available
                        / available_total
                    )

                remaining -= change

        # --------------------------------------------------------------
        # REMOVE TIME
        # --------------------------------------------------------------

        else:
            remaining = (
                total
                - target_duration_seconds
            )

            while remaining > 0.000001:
                adjustable = [
                    i
                    for i, duration
                    in enumerate(durations)
                    if (
                        duration
                        > self.MIN_SCENE_DURATION
                        + 0.000001
                    )
                ]

                if not adjustable:
                    raise ValueError(
                        "Unable to reduce storyboard duration."
                    )

                available_total = sum(
                    durations[i]
                    - self.MIN_SCENE_DURATION
                    for i in adjustable
                )

                change = min(
                    remaining,
                    available_total,
                )

                for i in adjustable:
                    available = (
                        durations[i]
                        - self.MIN_SCENE_DURATION
                    )

                    durations[i] -= (
                        change
                        * available
                        / available_total
                    )

                remaining -= change

        fitted: list[StoryboardScene] = []

        current_start = 0.0

        for scene, duration in zip(
            scenes,
            durations,
        ):
            fitted.append(
                scene.model_copy(
                    update={
                        "start_seconds": current_start,
                        "duration_seconds": duration,
                    }
                )
            )

            current_start += duration

        drift = (
            target_duration_seconds
            - current_start
        )

        if abs(drift) > 0.000001:
            last = fitted[-1]

            corrected = (
                last.duration_seconds
                + drift
            )

            if not (
                self.MIN_SCENE_DURATION
                <= corrected
                <= self.MAX_SCENE_DURATION
            ):
                raise ValueError(
                    "Final duration correction would violate "
                    "the 1–3 second scene duration limits."
                )

            fitted[-1] = last.model_copy(
                update={
                    "duration_seconds": corrected
                }
            )

        return self._rebuild_timeline(
            fitted
        )

    def _rebuild_timeline(
        self,
        scenes: list[StoryboardScene],
    ) -> list[StoryboardScene]:
        rebuilt: list[StoryboardScene] = []

        current_start = 0.0

        for scene in scenes:
            updated = scene.model_copy(
                update={
                    "start_seconds": current_start
                }
            )

            rebuilt.append(updated)

            current_start += (
                updated.duration_seconds
            )

        return rebuilt

    # ======================================================================
    # IMAGE PROMPTS
    # ======================================================================

    def _rebuild_prompts(
        self,
        scenes: list[StoryboardScene],
        topic: str | None = None,
    ) -> list[StoryboardScene]:
        rebuilt: list[StoryboardScene] = []

        for scene in scenes:
            prompt = self.prompt_builder.build(
                scene
            )

            rebuilt.append(
                scene.model_copy(
                    update={
                        "image_prompt": prompt,
                        "camera_motion": "static",
                        "transition": "cut",
                    }
                )
            )

        return rebuilt

    # ======================================================================
    # FINAL VALIDATION
    # ======================================================================

    def _validate_dynamic_scenes(
        self,
        scenes: list[StoryboardScene],
        target_duration_seconds: float,
    ) -> None:
        if not scenes:
            raise ValueError(
                "Dynamic storyboard has no scenes."
            )

        final_duration = sum(
            scene.duration_seconds
            for scene in scenes
        )

        if abs(
            final_duration
            - target_duration_seconds
        ) > 0.001:
            raise ValueError(
                "Dynamic storyboard duration mismatch: "
                f"{final_duration:.3f}s != "
                f"{target_duration_seconds:.3f}s"
            )

        previous_end = 0.0

        for expected_index, scene in enumerate(
            scenes,
            start=1,
        ):
            expected_id = (
                f"scene_{expected_index:03d}"
            )

            if scene.scene_id != expected_id:
                raise ValueError(
                    f"Unexpected scene ID "
                    f"{scene.scene_id}; "
                    f"expected {expected_id}."
                )

            if not (
                self.MIN_SCENE_DURATION
                <= scene.duration_seconds
                <= self.MAX_SCENE_DURATION
            ):
                raise ValueError(
                    f"Scene {scene.scene_id} duration "
                    f"{scene.duration_seconds:.3f}s is outside "
                    f"the allowed range "
                    f"{self.MIN_SCENE_DURATION:.3f}s–"
                    f"{self.MAX_SCENE_DURATION:.3f}s."
                )

            if abs(
                scene.start_seconds
                - previous_end
            ) > 0.001:
                raise ValueError(
                    f"Timeline gap/overlap detected at "
                    f"{scene.scene_id}."
                )

            if scene.camera_motion != "static":
                raise ValueError(
                    f"{scene.scene_id} must use "
                    "a static camera."
                )

            if scene.transition != "cut":
                raise ValueError(
                    f"{scene.scene_id} must use "
                    "a hard cut."
                )

            if not scene.narration.strip():
                raise ValueError(
                    f"{scene.scene_id} has empty narration."
                )

            if not scene.visual_description.strip():
                raise ValueError(
                    f"{scene.scene_id} has empty visual description."
                )

            if not scene.image_prompt.strip():
                raise ValueError(
                    f"{scene.scene_id} has empty image prompt."
                )

            if scene.text_overlay:
                if not self._is_production_editorial_text(
                    scene.text_overlay
                ):
                    raise ValueError(
                        f"Invalid production editorial text in "
                        f"{scene.scene_id}: "
                        f"{scene.text_overlay!r}"
                    )

            previous_end = (
                scene.start_seconds
                + scene.duration_seconds
            )

        if abs(
            previous_end
            - target_duration_seconds
        ) > 0.001:
            raise ValueError(
                "Storyboard end time does not match "
                f"target duration: "
                f"{previous_end:.3f}s != "
                f"{target_duration_seconds:.3f}s"
            )