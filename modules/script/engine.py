import json
import os
import re
from pathlib import Path

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.outline.models import Outline
from modules.project.config import ProductionConfig
from modules.research.models import Research
from modules.script.models import Script
from modules.script.hook_quality import HookQualityReview


class ScriptEngine:
    """Generates narration scripts from approved research and outlines."""

    # ---------------------------------------------------------
    # Script requirements
    # ---------------------------------------------------------

    WORDS_PER_MINUTE = 140
    TEN_SECOND_HOOK_WORDS = 25

    MINIMUM_DURATION_SECONDS = 480

    MINIMUM_WORD_COUNT = 1150

    MAX_GENERATION_ATTEMPTS = 3

    # ---------------------------------------------------------
    # Initialization
    # ---------------------------------------------------------

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=OPENAI_API_KEY
        )

    # ---------------------------------------------------------
    # Create script
    # ---------------------------------------------------------

    def create_script(
        self,
        research_file: Path,
        outline_file: Path,
        script_directory: Path,
        force_refresh: bool = False,
        production_config: ProductionConfig | None = None,
        qa_feedback: str | None = None,
    ) -> Script:
        """Generate a narration script from research and outline."""

        script_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        script_file = (
            script_directory / "script.json"
        )

        # -------------------------------------------------
        # Cache
        # -------------------------------------------------

        if (
            script_file.exists()
            and not force_refresh
        ):
            return self._load_script(
                script_file
            )

        # -------------------------------------------------
        # Load approved inputs
        # -------------------------------------------------

        research = self._load_research(
            research_file
        )

        outline = self._load_outline(
            outline_file
        )

        # -------------------------------------------------
        # Validate input topics
        # -------------------------------------------------

        if research.topic != outline.topic:
            raise ValueError(
                "Research and outline topics do not match."
            )

        # -------------------------------------------------
        # Generate script with retries
        # -------------------------------------------------

        config = production_config or ProductionConfig()
        minimum_word_count = config.minimum_word_count
        maximum_duration_seconds = config.maximum_acceptable_duration_seconds
        last_word_count = 0

        for attempt in range(
            1,
            self.MAX_GENERATION_ATTEMPTS + 1,
        ):
            print(
                f"Generating script "
                f"(attempt {attempt}/"
                f"{self.MAX_GENERATION_ATTEMPTS})..."
            )

            # ---------------------------------------------
            # First generation
            # ---------------------------------------------

            if attempt == 1:
                user_prompt = self._build_user_prompt(
                    research,
                    outline,
                    config,
                )

            # ---------------------------------------------
            # Corrective generation
            # ---------------------------------------------

            elif last_word_count and self._calculate_duration_seconds(
                last_word_count
            ) > maximum_duration_seconds:
                user_prompt = self._build_contraction_prompt(
                    research,
                    outline,
                    last_word_count,
                    config,
                )
            else:
                user_prompt = self._build_expansion_prompt(
                    research,
                    outline,
                    last_word_count,
                    config,
                )
            if qa_feedback:
                user_prompt = (
                    f"{user_prompt}\n\n"
                    "QA issues to correct in this revision:\n"
                    f"{qa_feedback}"
                )

            # ---------------------------------------------
            # OpenAI structured generation
            # ---------------------------------------------

            response = self.client.responses.parse(
                model=OPENAI_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": self._system_prompt(config),
                    },
                    {
                        "role": "user",
                        "content": user_prompt,
                    },
                ],
                text_format=Script,
            )

            script = response.output_parsed

            if script is None:
                raise RuntimeError(
                    "OpenAI returned no structured script."
                )

            # ---------------------------------------------
            # Calculate actual word count
            # ---------------------------------------------

            actual_word_count = (
                self._calculate_word_count(
                    script
                )
            )

            last_word_count = actual_word_count

            # ---------------------------------------------
            # Calculate actual duration
            # ---------------------------------------------

            actual_duration_seconds = (
                self._calculate_duration_seconds(
                    actual_word_count
                )
            )

            # ---------------------------------------------
            # Replace model-generated metadata
            # ---------------------------------------------

            script = script.model_copy(
                update={
                    "target_duration_seconds": config.target_duration_seconds,
                    "target_word_count": minimum_word_count,
                    "total_word_count": (
                        actual_word_count
                    ),
                    "total_estimated_seconds": (
                        actual_duration_seconds
                    ),
                }
            )

            print(
                f"Generated "
                f"{actual_word_count} words "
                f"({actual_duration_seconds}s)."
            )

            # ---------------------------------------------
            # Check minimum requirements
            # ---------------------------------------------

            if (
                actual_word_count
                >= minimum_word_count
                and actual_duration_seconds
                >= config.minimum_duration_seconds
                and actual_duration_seconds
                <= maximum_duration_seconds
            ):
                script = self._review_and_strengthen_hook(
                    script,
                    research,
                    script_directory,
                )

                # -----------------------------------------
                # Full validation
                # -----------------------------------------

                self._validate_script(
                    script,
                    research,
                    outline,
                    minimum_word_count=minimum_word_count,
                    minimum_duration_seconds=(
                        config.minimum_duration_seconds
                    ),
                )

                # -----------------------------------------
                # Save
                # -----------------------------------------

                self._save_script(
                    script_file,
                    script,
                )

                return script

            print("Script duration is outside configured limits. Retrying...")

        # -------------------------------------------------
        # All attempts failed
        # -------------------------------------------------

        raise ValueError(
            "Unable to generate a script within configured duration limits "
            f"after {self.MAX_GENERATION_ATTEMPTS} "
            f"attempts. "
            f"Last result contained "
            f"{last_word_count} words."
        )

    def _review_and_strengthen_hook(
        self,
        script: Script,
        research: Research,
        script_directory: Path,
    ) -> Script:
        threshold_text = os.getenv("RITZZ_HOOK_MIN_SCORE", "3.5")
        try:
            threshold = float(threshold_text)
        except ValueError as exc:
            raise ValueError("RITZZ_HOOK_MIN_SCORE must be a number from 0 to 5.") from exc
        if not 0 <= threshold <= 5:
            raise ValueError("RITZZ_HOOK_MIN_SCORE must be a number from 0 to 5.")

        source_ids = {source.id for source in research.sources}
        report: dict = {
            "version": 1,
            "topic": script.topic,
            "threshold": threshold,
            "original_hook": script.hook,
            "selected_hook": script.hook,
            "iterations": [],
        }
        report_path = script_directory / "hook_evaluation.json"

        for iteration in range(1, 3):
            hook_section = next(
                (
                    section
                    for section in script.sections
                    if section.section_type == "hook"
                ),
                script.sections[0] if script.sections else None,
            )
            if hook_section is None:
                raise ValueError("Cannot evaluate a hook without script sections.")
            response = self.client.responses.parse(
                model=OPENAI_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Evaluate and improve a fact-grounded YouTube opening hook. "
                            "Score curiosity, tension, specificity, stakes, novelty, clarity, "
                            "open loop, payoff promise, and factual support from 0 to 5. "
                            "Do not use simplistic banned-phrase rules. Judge whether the "
                            "actual opening earns attention and promises a supported answer. "
                            "Provide three distinct, stronger alternatives when the current "
                            "hook is weak. Each alternative must be 13–38 spoken words and "
                            "cite source IDs that support its claims. Do not rewrite the "
                            "script or reveal the full answer in the hook."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Current hook:\n{script.hook}\n\n"
                            "Opening section context:\n"
                            f"{hook_section.narration}\n\n"
                            "Approved research and source IDs:\n"
                            f"{research.model_dump_json(indent=2)}\n\n"
                            f"Minimum average quality score: {threshold:.2f}/5.\n"
                            "Return scores for the current hook and three alternatives. "
                            "If prior alternatives were supplied, do not repeat their wording; "
                            "address the prior weaknesses."
                            + (
                                "\n\nPreviously attempted alternatives:\n"
                                + json.dumps(report["iterations"], ensure_ascii=False)
                                if report["iterations"]
                                else ""
                            )
                        ),
                    },
                ],
                text_format=HookQualityReview,
            )
            review = response.output_parsed
            if not isinstance(review, HookQualityReview):
                raise RuntimeError("Hook evaluator returned no valid structured result.")
            if review.current.text.strip().casefold() != script.hook.strip().casefold():
                raise ValueError(
                    "Hook evaluator scored a different current hook than the script contains."
                )
            current = review.current
            valid_alternatives = [
                candidate
                for candidate in review.alternatives
                if 13 <= self._count_words(candidate.text) <= 38
                and candidate.factual_support >= 4
                and candidate.source_ids
                and set(candidate.source_ids).issubset(source_ids)
            ]
            iteration_result = {
                "iteration": iteration,
                "current": current.model_dump(mode="json"),
                "current_score": current.quality_score,
                "alternatives": [
                    {
                        **candidate.model_dump(mode="json"),
                        "quality_score": candidate.quality_score,
                        "word_count": self._count_words(candidate.text),
                        "eligible": candidate in valid_alternatives,
                    }
                    for candidate in review.alternatives
                ],
                "improvement_notes": review.improvement_notes,
            }
            report["iterations"].append(iteration_result)

            current_is_supported = (
                current.factual_support >= 4
                and (
                    not current.source_ids
                    or set(current.source_ids).issubset(source_ids)
                )
            )
            if current.quality_score >= threshold and current_is_supported:
                report["status"] = "PASS"
                report["selected_hook"] = script.hook
                report["regenerated"] = script.hook != report["original_hook"]
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                self._save_script(script_directory / "script.json", script)
                return script

            qualified_alternatives = [
                candidate
                for candidate in valid_alternatives
                if candidate.quality_score >= threshold
            ]
            if not qualified_alternatives:
                qualified_alternatives = [
                    candidate
                    for candidate in valid_alternatives
                    if candidate.quality_score > current.quality_score
                ]
            if not qualified_alternatives:
                report["status"] = "FAIL"
                report["failure"] = (
                    "No fact-supported alternative improved the hook within "
                    "the required 13–38 word range."
                )
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                raise ValueError(
                    "Hook quality remained below threshold and no fact-supported "
                    "13–38-word alternative improved it; inspect hook_evaluation.json."
                )
            selected = max(
                qualified_alternatives,
                key=lambda candidate: candidate.quality_score,
            )
            script = self._replace_opening_hook(script, selected.text)
            report["selected_hook"] = selected.text
            if selected.quality_score >= threshold:
                report["status"] = "PASS"
                report["regenerated"] = selected.text != report["original_hook"]
                report_path.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                self._save_script(script_directory / "script.json", script)
                return script

        report["status"] = "FAIL"
        report["failure"] = "Hook remained below the configured quality threshold."
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        raise ValueError(
            "Hook remained below the configured quality threshold after "
            "two hook-only improvement attempts; inspect hook_evaluation.json."
        )

    @classmethod
    def _replace_opening_hook(cls, script: Script, new_hook: str) -> Script:
        if not script.sections or not new_hook.strip():
            raise ValueError("Cannot replace a missing opening hook.")
        hook_section_index = next(
            (
                index
                for index, section in enumerate(script.sections)
                if section.section_type == "hook"
            ),
            0,
        )
        section = script.sections[hook_section_index]
        leading = len(section.narration) - len(section.narration.lstrip())
        narration = section.narration[leading:]
        if not narration.casefold().startswith(script.hook.strip().casefold()):
            raise ValueError(
                "Script.hook does not match the first spoken hook-section text; "
                "cannot safely regenerate only the hook."
            )
        remainder = narration[len(script.hook.strip()):].lstrip()
        updated_narration = (
            f"{new_hook.strip()} {remainder}".rstrip()
            if remainder
            else new_hook.strip()
        )
        sections = list(script.sections)
        sections[hook_section_index] = section.model_copy(
            update={"narration": " " * leading + updated_narration}
        )
        updated_script = script.model_copy(
            update={
                "hook": new_hook.strip(),
                "sections": sections,
            }
        )
        word_count = cls._calculate_word_count(updated_script)
        return updated_script.model_copy(
            update={
                "total_word_count": word_count,
                "total_estimated_seconds": cls._calculate_duration_seconds(word_count),
            }
        )

    # ---------------------------------------------------------
    # System prompt
    # ---------------------------------------------------------

    @staticmethod
    def _system_prompt(config: ProductionConfig | None = None) -> str:
        """Return the Script Engine system prompt."""

        config = config or ProductionConfig()
        target_words = round(
            config.target_duration_seconds
            * ScriptEngine.WORDS_PER_MINUTE
            / 60
        )
        maximum_words = round(
            config.maximum_acceptable_duration_seconds
            * ScriptEngine.WORDS_PER_MINUTE
            / 60
        )

        return (
            "You are the Script Engine for Ritzz, "
            "an English-language educational YouTube channel.\n\n"

            "Your job is to transform approved research "
            "and an approved video outline into a complete "
            "engaging narration script.\n\n"

            f"The script is intended for an approximately {config.target_duration_seconds // 60}-minute YouTube video.\n\n"

            f"Aim for about {target_words} spoken words and do not exceed {maximum_words} words unless the approved research cannot be explained accurately within that length.\n\n"

            f"The first spoken words of the first hook section must be a compelling hook of about {ScriptEngine.TEN_SECOND_HOOK_WORDS} words (roughly 10 seconds). Start with a vivid question, surprising contrast, or specific curiosity gap that is supported by the research. Build interest without giving away the full answer. Avoid greetings, channel introductions, generic setup, and unsupported or exaggerated claims. The Script.hook field must match this opening text; the voice reads the section narration, so do not repeat the hook later.\n\n"

            "The final narration MUST contain at least "
            f"{config.minimum_word_count} words of actual spoken narration.\n\n"

            "Use approximately 140 spoken words per minute "
            "as the pacing reference.\n\n"

            "Write natural spoken English suitable for "
            "professional YouTube narration and text-to-speech.\n\n"

            "Use careful standard punctuation to guide calm spoken delivery: "
            "commas for natural clause pauses, periods when a thought is complete, "
            "and question marks for genuine questions. Break paragraphs at meaningful "
            "story transitions. Avoid run-on sentences, sentence fragments, and "
            "repeated ellipses or exclamation marks. Do not put spoken delivery or "
            "stage directions in the narration.\n\n"

            "The writing should sound like a skilled human "
            "YouTube narrator rather than an academic paper.\n\n"

            "Use curiosity, pacing, transitions, explanations "
            "and storytelling.\n\n"

            "Fully develop every section of the outline.\n\n"

            "Do not produce a short summary.\n\n"

            "Do not compress multiple ideas into a few sentences "
            "just to move quickly through the outline.\n\n"

            "Each section should contain enough narration to "
            "reasonably fill its allocated duration.\n\n"

            "Do not invent factual claims.\n\n"

            "Use ONLY information supported by the supplied "
            "research.\n\n"

            "Do not introduce unsupported dates, names, events, "
            "statistics or explanations.\n\n"

            "If the research describes something as uncertain, "
            "unproven, disputed or a theory, preserve that "
            "level of uncertainty in the narration.\n\n"

            "Follow the supplied outline structure exactly.\n\n"

            "Preserve the research source IDs associated with "
            "each outline section.\n\n"

            "Source IDs are production metadata and should not "
            "normally be spoken aloud.\n\n"

            "The narration should feel like one continuous "
            "YouTube story with natural transitions between "
            "sections.\n\n"

            "Do not include stage directions, camera directions, "
            "visual instructions or production notes inside "
            "the narration."
        )

    # ---------------------------------------------------------
    # First-generation user prompt
    # ---------------------------------------------------------

    @classmethod
    def _build_user_prompt(
        cls,
        research: Research,
        outline: Outline,
        config: ProductionConfig | None = None,
    ) -> str:
        """Build the initial generation prompt."""

        config = config or ProductionConfig()
        target_words = round(
            config.target_duration_seconds
            * cls.WORDS_PER_MINUTE
            / 60
        )
        maximum_words = round(
            config.maximum_acceptable_duration_seconds
            * cls.WORDS_PER_MINUTE
            / 60
        )
        section_targets = []

        for section in outline.sections:
            target_words = round(
                section.estimated_seconds
                * cls.WORDS_PER_MINUTE
                / 60
            )

            section_targets.append(
                f"- {section.section_id}: "
                f"{section.title} — "
                f"{section.estimated_seconds} seconds, "
                f"approximately {target_words} words"
            )

        section_target_text = "\n".join(
            section_targets
        )

        return (
            "Create the final narration script using ONLY "
            "the approved research and outline below.\n\n"

            "=================================================\n"
            "SCRIPT LENGTH REQUIREMENTS\n"
            "=================================================\n\n"

            f"TARGET: approximately {target_words} spoken words ({config.target_duration_seconds} seconds).\n"
            f"HARD UPPER LIMIT: {maximum_words} words ({config.maximum_acceptable_duration_seconds} seconds).\n"
            f"The narration must meet the configured minimum of {config.minimum_word_count} words.\n\n"

            f"OPENING HOOK: The first spoken words of the first hook section must be a compelling, fact-grounded hook of about {cls.TEN_SECOND_HOOK_WORDS} spoken words (roughly 10 seconds). Use a specific curiosity gap, surprising contrast, or question; do not give away the full answer. No greeting, channel introduction, generic setup, or unsupported/exaggerated claim. The Script.hook field must match this opening text exactly; narration speaks it once, so do not repeat the hook later.\n\n"

            "Use approximately 140 spoken words per minute "
            "as the pacing reference.\n\n"

            "Punctuate every narration section for natural text-to-speech: use commas "
            "for brief clause pauses, periods for completed thoughts, and question "
            "marks for real questions. Avoid run-on sentences, fragments, and excess "
            "ellipses or exclamation marks.\n\n"

            "Do not intentionally write a short script.\n\n"

            "Fully develop every section rather than merely "
            "mentioning its key points.\n\n"

            "Approximate word targets for each section:\n\n"

            f"{section_target_text}\n\n"

            "These are approximate targets. Natural storytelling "
            "and factual accuracy are more important than exact "
            "section word counts.\n\n"

            "If a section needs additional words to explain "
            "its idea clearly, expand it naturally.\n\n"

            "Do NOT add unsupported information merely to "
            "increase the word count.\n\n"

            "=================================================\n"
            "APPROVED RESEARCH\n"
            "=================================================\n\n"

            f"{research.model_dump_json(indent=2)}\n\n"

            "=================================================\n"
            "APPROVED OUTLINE\n"
            "=================================================\n\n"

            f"{outline.model_dump_json(indent=2)}"
        )

    @classmethod
    def _build_contraction_prompt(
        cls,
        research: Research,
        outline: Outline,
        current_word_count: int,
        config: ProductionConfig,
    ) -> str:
        maximum_words = round(
            config.maximum_acceptable_duration_seconds
            * cls.WORDS_PER_MINUTE
            / 60
        )
        return (
            "The previous script exceeded the configured video duration.\n\n"
            f"It contained {current_word_count} words. Rewrite the COMPLETE script "
            f"to contain approximately {config.minimum_word_count} words and no more "
            f"than {maximum_words} words. Keep every outline section, preserve source "
            "IDs, and retain all important supported facts. Remove repetition, "
            "redundant transitions, and nonessential detail; do not invent facts.\n\n"
            f"Preserve a compelling, fact-grounded opening hook of about {cls.TEN_SECOND_HOOK_WORDS} words at the beginning of the first hook section. Keep Script.hook exactly matched to those first spoken words; do not repeat the hook later.\n\n"
            "Use only the approved research and follow the approved outline.\n\n"
            "APPROVED RESEARCH:\n"
            f"{research.model_dump_json(indent=2)}\n\n"
            "APPROVED OUTLINE:\n"
            f"{outline.model_dump_json(indent=2)}"
        )

    # ---------------------------------------------------------
    # Expansion prompt
    # ---------------------------------------------------------

    @classmethod
    def _build_expansion_prompt(
        cls,
        research: Research,
        outline: Outline,
        current_word_count: int,
        config: ProductionConfig | None = None,
    ) -> str:
        """Build a prompt for expanding an undersized script."""

        required_words = (config or ProductionConfig()).minimum_word_count

        additional_words = (
            required_words
            - current_word_count
        )

        additional_words = max(additional_words, 0)

        requested_additional_words = (
            additional_words + 100
        )

        return (
            "The previous generated script was too short.\n\n"

            f"The previous script contained "
            f"{current_word_count} words.\n\n"

            f"The final script MUST contain at least "
            f"{required_words} words.\n\n"

            f"Add approximately "
            f"{requested_additional_words} "
            "additional words while maintaining natural "
            "YouTube narration.\n\n"

            "IMPORTANT:\n"
            "Generate the COMPLETE script again. "
            "Do not return only the additional paragraphs.\n\n"

            f"Preserve the compelling, fact-grounded opening hook of about {cls.TEN_SECOND_HOOK_WORDS} words at the beginning of the first hook section. Keep Script.hook exactly matched to those first spoken words; do not repeat the hook later.\n\n"

            "Fully preserve all existing sections.\n\n"

            "Expand the script naturally by developing:\n"
            "- explanations\n"
            "- context\n"
            "- transitions\n"
            "- examples already supported by the research\n"
            "- historical detail already present in the research\n"
            "- myth-versus-fact explanations\n"
            "- storytelling and narrative flow\n\n"

            "Do NOT pad the script with repetition.\n\n"

            "Do NOT repeat the same point using different words "
            "just to increase length.\n\n"

            "Do NOT introduce unsupported facts.\n\n"

            "Use ONLY the approved research below.\n\n"

            "Maintain the exact outline section structure.\n\n"

            "Maintain the research source IDs associated with "
            "each section.\n\n"

            "Punctuate every narration section for natural text-to-speech: use commas "
            "for brief clause pauses, periods for completed thoughts, and question "
            "marks for real questions. Avoid run-on sentences, fragments, and excess "
            "ellipses or exclamation marks.\n\n"

            "The result must contain at least "
            f"{required_words} words of actual narration.\n\n"

            "=================================================\n"
            "APPROVED RESEARCH\n"
            "=================================================\n\n"

            f"{research.model_dump_json(indent=2)}\n\n"

            "=================================================\n"
            "APPROVED OUTLINE\n"
            "=================================================\n\n"

            f"{outline.model_dump_json(indent=2)}"
        )

    # ---------------------------------------------------------
    # Research loading
    # ---------------------------------------------------------

    @staticmethod
    def _load_research(
        research_file: Path,
    ) -> Research:
        """Load and validate research JSON."""

        if not research_file.exists():
            raise FileNotFoundError(
                f"Research file not found: "
                f"{research_file}"
            )

        data = json.loads(
            research_file.read_text(
                encoding="utf-8"
            )
        )

        return Research.model_validate(
            data
        )

    # ---------------------------------------------------------
    # Outline loading
    # ---------------------------------------------------------

    @staticmethod
    def _load_outline(
        outline_file: Path,
    ) -> Outline:
        """Load and validate outline JSON."""

        if not outline_file.exists():
            raise FileNotFoundError(
                f"Outline file not found: "
                f"{outline_file}"
            )

        data = json.loads(
            outline_file.read_text(
                encoding="utf-8"
            )
        )

        return Outline.model_validate(
            data
        )

    # ---------------------------------------------------------
    # Script saving
    # ---------------------------------------------------------

    @staticmethod
    def _save_script(
        script_file: Path,
        script: Script,
    ) -> None:
        """Save the generated script."""

        script_file.write_text(
            script.model_dump_json(
                indent=4
            ),
            encoding="utf-8",
        )

    # ---------------------------------------------------------
    # Script loading
    # ---------------------------------------------------------

    @staticmethod
    def _load_script(
        script_file: Path,
    ) -> Script:
        """Load a cached script."""

        data = json.loads(
            script_file.read_text(
                encoding="utf-8"
            )
        )

        return Script.model_validate(
            data
        )

    # ---------------------------------------------------------
    # Word counting
    # ---------------------------------------------------------

    @staticmethod
    def _count_words(
        text: str,
    ) -> int:
        """Count spoken words."""

        return len(
            re.findall(
                r"\b[\w’'-]+\b",
                text,
            )
        )

    @classmethod
    def _calculate_word_count(
        cls,
        script: Script,
    ) -> int:
        """Calculate total narration word count."""

        narration = " ".join(
            section.narration
            for section in script.sections
        )

        return cls._count_words(
            narration
        )

    # ---------------------------------------------------------
    # Duration calculation
    # ---------------------------------------------------------

    @classmethod
    def _calculate_duration_seconds(
        cls,
        word_count: int,
    ) -> int:
        """Calculate narration duration from word count."""

        seconds = (
            word_count
            / cls.WORDS_PER_MINUTE
            * 60
        )

        return round(seconds)

    # ---------------------------------------------------------
    # Script validation
    # ---------------------------------------------------------

    @classmethod
    def _validate_script(
        cls,
        script: Script,
        research: Research,
        outline: Outline,
        minimum_word_count: int | None = None,
        minimum_duration_seconds: int | None = None,
    ) -> None:
        """Validate the generated script."""

        required_word_count = (
            minimum_word_count
            if minimum_word_count is not None
            else cls.MINIMUM_WORD_COUNT
        )
        required_duration_seconds = (
            minimum_duration_seconds
            if minimum_duration_seconds is not None
            else cls.MINIMUM_DURATION_SECONDS
        )

        # -------------------------------------------------
        # Topic validation
        # -------------------------------------------------

        if script.topic != research.topic:
            raise ValueError(
                "Script topic does not match "
                "research topic."
            )

        if script.topic != outline.topic:
            raise ValueError(
                "Script topic does not match "
                "outline topic."
            )

        # -------------------------------------------------
        # Section validation
        # -------------------------------------------------

        if not script.sections:
            raise ValueError(
                "Script must contain at least one section."
            )

        if len(script.sections) != len(
            outline.sections
        ):
            raise ValueError(
                "Script section count does not match "
                "outline section count."
            )

        # -------------------------------------------------
        # Section IDs
        # -------------------------------------------------

        outline_ids = [
            section.section_id
            for section in outline.sections
        ]

        script_ids = [
            section.section_id
            for section in script.sections
        ]

        if script_ids != outline_ids:
            raise ValueError(
                "Script section IDs do not match "
                "the outline."
            )

        # -------------------------------------------------
        # Narration validation
        # -------------------------------------------------

        for section in script.sections:
            if not section.narration.strip():
                raise ValueError(
                    f"Section {section.section_id} "
                    "contains no narration."
                )

        # -------------------------------------------------
        # Word count
        # -------------------------------------------------

        calculated_words = (
            cls._calculate_word_count(
                script
            )
        )

        if calculated_words != (
            script.total_word_count
        ):
            raise ValueError(
                "Script word count mismatch: "
                f"calculated {calculated_words}, "
                f"but script reports "
                f"{script.total_word_count}."
            )

        # -------------------------------------------------
        # Minimum word count
        # -------------------------------------------------

        if calculated_words < required_word_count:
            raise ValueError(
                "Script is too short: "
                f"{calculated_words} words generated, "
                f"but at least "
                f"{required_word_count} words "
                "are required."
            )

        # -------------------------------------------------
        # Duration
        # -------------------------------------------------

        calculated_duration = (
            cls._calculate_duration_seconds(
                calculated_words
            )
        )

        if calculated_duration != (
            script.total_estimated_seconds
        ):
            raise ValueError(
                "Script duration mismatch: "
                f"calculated {calculated_duration}s, "
                f"but script reports "
                f"{script.total_estimated_seconds}s."
            )

        # -------------------------------------------------
        # Minimum duration
        # -------------------------------------------------

        if calculated_duration < required_duration_seconds:
            raise ValueError(
                "Script is too short: "
                f"calculated duration is "
                f"{calculated_duration}s, "
                f"but at least "
                f"{required_duration_seconds}s "
                "is required."
            )
