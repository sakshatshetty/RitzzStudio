import json
from pathlib import Path

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.outline.models import Outline
from modules.research.models import Research


class OutlineEngine:
    """Generates structured video outlines from research."""

    def __init__(self) -> None:
        self.client = OpenAI(api_key=OPENAI_API_KEY)

    def create_outline(
        self,
        research_file: Path,
        outline_directory: Path,
        force_refresh: bool = False,
    ) -> Outline:
        """
        Generate an outline from a research JSON file.

        Existing outline.json is reused unless force_refresh
        is True.
        """

        outline_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        outline_file = outline_directory / "outline.json"

        # -------------------------------------------------
        # Cache
        # -------------------------------------------------

        if outline_file.exists() and not force_refresh:
            return self._load_outline(outline_file)

        # -------------------------------------------------
        # Load research
        # -------------------------------------------------

        research = self._load_research(research_file)

        # -------------------------------------------------
        # Generate outline
        # -------------------------------------------------

        response = self.client.responses.parse(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": self._system_prompt(),
                },
                {
                    "role": "user",
                    "content": self._build_user_prompt(research),
                },
            ],
            text_format=Outline,
        )

        outline = response.output_parsed

        if outline is None:
            raise RuntimeError(
                "OpenAI returned no structured outline."
            )

        # -------------------------------------------------
        # Validate duration
        # -------------------------------------------------

        self._validate_duration(outline)

        # -------------------------------------------------
        # Save
        # -------------------------------------------------

        self._save_outline(
            outline_file,
            outline,
        )

        return outline

    @staticmethod
    def _system_prompt() -> str:
        """Return the editorial system prompt."""

        return (
            "You are the Outline Engine for Ritzz, "
            "an educational YouTube channel.\n\n"

            "Create an engaging approximately 8-minute "
            "YouTube video outline from the supplied research.\n\n"

            "The audience is a general curious audience.\n\n"

            "The video should feel like a compelling explanation "
            "rather than an academic lecture.\n\n"

            "Use a strong curiosity-driven opening.\n\n"

            "Build a logical progression from question to explanation "
            "to surprising insight and payoff.\n\n"

            "Do not invent facts that are not supported by the research.\n\n"

            "Preserve the research source IDs when assigning "
            "sources to sections.\n\n"

            "Recommended structure:\n"
            "1. Hook\n"
            "2. Setup\n"
            "3. Main question\n"
            "4. Explanation\n"
            "5. Myth or surprising discovery\n"
            "6. Deeper context\n"
            "7. Payoff\n"
            "8. Conclusion\n\n"

            "The final outline should target approximately "
            "480 seconds."
        )

    @staticmethod
    def _build_user_prompt(
        research: Research,
    ) -> str:
        """Build the user prompt from structured research."""

        return (
            "Create a video outline using ONLY the research "
            "provided below.\n\n"
            "RESEARCH:\n"
            f"{research.model_dump_json(indent=2)}"
        )

    @staticmethod
    def _load_research(
        research_file: Path,
    ) -> Research:
        """Load and validate research JSON."""

        if not research_file.exists():
            raise FileNotFoundError(
                f"Research file not found: {research_file}"
            )

        data = json.loads(
            research_file.read_text(
                encoding="utf-8"
            )
        )

        return Research.model_validate(data)

    @staticmethod
    def _save_outline(
        outline_file: Path,
        outline: Outline,
    ) -> None:
        """Save outline as formatted JSON."""

        outline_file.write_text(
            outline.model_dump_json(indent=4),
            encoding="utf-8",
        )

    @staticmethod
    def _load_outline(
        outline_file: Path,
    ) -> Outline:
        """Load and validate cached outline."""

        data = json.loads(
            outline_file.read_text(
                encoding="utf-8"
            )
        )

        return Outline.model_validate(data)

    @staticmethod
    def _validate_duration(
        outline: Outline,
    ) -> None:
        """Validate the outline's estimated duration."""

        section_total = sum(
            section.estimated_seconds
            for section in outline.sections
        )

        if section_total != outline.total_estimated_seconds:
            raise ValueError(
                "Outline duration mismatch: "
                f"sections total {section_total}s, "
                f"but outline reports "
                f"{outline.total_estimated_seconds}s."
            )

        target = outline.target_duration_seconds

        # Allow approximately ±15% around the target.
        minimum = int(target * 0.85)
        maximum = int(target * 1.15)

        if not minimum <= section_total <= maximum:
            raise ValueError(
                "Outline duration is outside the acceptable range: "
                f"{section_total}s "
                f"(target: {target}s)."
            )