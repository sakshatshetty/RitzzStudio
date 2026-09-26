import json
from pathlib import Path

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.outline.models import Outline
from modules.project.config import ProductionConfig
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
        production_config: ProductionConfig | None = None,
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

        config = production_config or ProductionConfig()
        response = self.client.responses.parse(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": self._system_prompt(config),
                },
                {
                    "role": "user",
                    "content": self._build_user_prompt(research, config),
                },
            ],
            text_format=Outline,
        )

        outline = response.output_parsed

        if outline is None:
            raise RuntimeError(
                "OpenAI returned no structured outline."
            )

        outline = outline.model_copy(update={
            "target_duration_seconds": config.target_duration_seconds,
        })

        # -------------------------------------------------
        # Validate duration
        # -------------------------------------------------

        self._validate_duration(outline, config.target_duration_seconds)

        # -------------------------------------------------
        # Save
        # -------------------------------------------------

        self._save_outline(
            outline_file,
            outline,
        )

        return outline

    @staticmethod
    def _system_prompt(config: ProductionConfig | None = None) -> str:
        """Return the editorial system prompt."""

        target = (config or ProductionConfig()).target_duration_seconds
        minimum = int(target * 0.85)
        maximum = int(target * 1.15)

        return (
            "You are the Outline Engine for Ritzz, "
            "an educational YouTube channel.\n\n"

            f"Create an engaging approximately {target // 60}-minute "
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
            f"{target} seconds. The sum of all section durations "
            f"must be between {minimum} and {maximum} seconds."
        )

    @staticmethod
    def _build_user_prompt(
        research: Research,
        config: ProductionConfig | None = None,
    ) -> str:
        """Build the user prompt from structured research."""

        target = (config or ProductionConfig()).target_duration_seconds
        minimum = int(target * 0.85)
        maximum = int(target * 1.15)

        return (
            "Create a video outline using ONLY the research "
            "provided below.\n\n"
            f"TARGET DURATION: exactly {target} seconds.\n"
            f"The estimated_seconds values for all sections MUST sum to "
            f"exactly {target} seconds and remain between {minimum} and "
            f"{maximum} seconds. Set total_estimated_seconds to the same "
            "section sum. Treat these duration requirements as hard constraints.\n\n"
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
        target_duration_seconds: int = 480,
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

        target = target_duration_seconds

        # Allow approximately ±15% around the target.
        minimum = int(target * 0.85)
        maximum = int(target * 1.15)

        if not minimum <= section_total <= maximum:
            raise ValueError(
                "Outline duration is outside the acceptable range: "
                f"{section_total}s "
                f"(target: {target}s)."
            )
