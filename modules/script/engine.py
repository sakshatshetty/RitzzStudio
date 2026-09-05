import json
import re
from pathlib import Path

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.outline.models import Outline
from modules.research.models import Research
from modules.script.models import Script


class ScriptEngine:
    """Generates narration scripts from approved research and outlines."""

    # ---------------------------------------------------------
    # Script requirements
    # ---------------------------------------------------------

    WORDS_PER_MINUTE = 140

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
                )

            # ---------------------------------------------
            # Expansion generation
            # ---------------------------------------------

            else:
                user_prompt = self._build_expansion_prompt(
                    research,
                    outline,
                    last_word_count,
                )

            # ---------------------------------------------
            # OpenAI structured generation
            # ---------------------------------------------

            response = self.client.responses.parse(
                model=OPENAI_MODEL,
                input=[
                    {
                        "role": "system",
                        "content": self._system_prompt(),
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
                >= self.MINIMUM_WORD_COUNT
                and actual_duration_seconds
                >= self.MINIMUM_DURATION_SECONDS
            ):
                # -----------------------------------------
                # Full validation
                # -----------------------------------------

                self._validate_script(
                    script,
                    research,
                    outline,
                )

                # -----------------------------------------
                # Save
                # -----------------------------------------

                self._save_script(
                    script_file,
                    script,
                )

                return script

            print(
                "Script is below the minimum "
                "8-minute requirement. "
                "Expanding and retrying..."
            )

        # -------------------------------------------------
        # All attempts failed
        # -------------------------------------------------

        raise ValueError(
            "Unable to generate an 8-minute script "
            f"after {self.MAX_GENERATION_ATTEMPTS} "
            f"attempts. "
            f"Last result contained "
            f"{last_word_count} words."
        )

    # ---------------------------------------------------------
    # System prompt
    # ---------------------------------------------------------

    @staticmethod
    def _system_prompt() -> str:
        """Return the Script Engine system prompt."""

        return (
            "You are the Script Engine for Ritzz, "
            "an English-language educational YouTube channel.\n\n"

            "Your job is to transform approved research "
            "and an approved video outline into a complete "
            "engaging narration script.\n\n"

            "The script is intended for an approximately "
            "8-minute YouTube video.\n\n"

            "The final narration MUST contain at least "
            "1150 words of actual spoken narration.\n\n"

            "Use approximately 140 spoken words per minute "
            "as the pacing reference.\n\n"

            "Write natural spoken English suitable for "
            "professional YouTube narration and text-to-speech.\n\n"

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
    ) -> str:
        """Build the initial generation prompt."""

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

            "The video MUST be at least 8 minutes long.\n\n"

            "The final script MUST contain at least "
            "1150 words of actual spoken narration.\n\n"

            "Use approximately 140 spoken words per minute "
            "as the pacing reference.\n\n"

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

    # ---------------------------------------------------------
    # Expansion prompt
    # ---------------------------------------------------------

    @classmethod
    def _build_expansion_prompt(
        cls,
        research: Research,
        outline: Outline,
        current_word_count: int,
    ) -> str:
        """Build a prompt for expanding an undersized script."""

        required_words = cls.MINIMUM_WORD_COUNT

        additional_words = (
            required_words
            - current_word_count
        )

        if additional_words < 0:
            additional_words = 0

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
    ) -> None:
        """Validate the generated script."""

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

        if calculated_words < (
            cls.MINIMUM_WORD_COUNT
        ):
            raise ValueError(
                "Script is too short: "
                f"{calculated_words} words generated, "
                f"but at least "
                f"{cls.MINIMUM_WORD_COUNT} words "
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

        if calculated_duration < (
            cls.MINIMUM_DURATION_SECONDS
        ):
            raise ValueError(
                "Script is too short: "
                f"calculated duration is "
                f"{calculated_duration}s, "
                f"but at least "
                f"{cls.MINIMUM_DURATION_SECONDS}s "
                "is required."
            )