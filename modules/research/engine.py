import json
from pathlib import Path

from openai import OpenAI

from config import OPENAI_API_KEY, OPENAI_MODEL
from modules.research.models import Research


class ResearchEngine:
    """Generates and manages structured research for Ritzz projects."""

    def __init__(self) -> None:
        self.client = OpenAI(api_key=OPENAI_API_KEY)

    def research(
        self,
        topic: str,
        research_directory: Path,
        force_refresh: bool = False,
    ) -> Research:
        """
        Research a topic and save the structured result.

        If cached research exists, it is reused unless force_refresh
        is True.
        """

        research_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        research_file = research_directory / "research.json"

        # -------------------------------------------------
        # Cache
        # -------------------------------------------------

        if research_file.exists() and not force_refresh:
            return self._load_research(research_file)

        # -------------------------------------------------
        # AI Research
        # -------------------------------------------------

        response = self.client.responses.parse(
            model=OPENAI_MODEL,
            tools=[
                {
                    "type": "web_search",
                }
            ],
            input=[
                {
                    "role": "system",
                    "content": self._system_prompt(),
                },
                {
                    "role": "user",
                    "content": (
                        f"Research this topic for a Ritzz video:\n\n"
                        f"{topic}"
                    ),
                },
            ],
            text_format=Research,
        )

        research = response.output_parsed

        if research is None:
            raise RuntimeError(
                "OpenAI returned no structured research."
            )

        # -------------------------------------------------
        # Normalize source IDs
        # -------------------------------------------------

        research = self._normalize_source_ids(research)

        # -------------------------------------------------
        # Save
        # -------------------------------------------------

        self._save_research(
            research_file,
            research,
        )

        return research

    @staticmethod
    def _system_prompt() -> str:
        """Return the research system prompt."""

        return (
            "You are the research engine for Ritzz, "
            "an educational YouTube channel.\n\n"

            "Research the requested topic carefully using web sources.\n\n"

            "Separate established facts from popular theories, "
            "opinions, and myths.\n\n"

            "Do not invent facts or sources.\n\n"

            "Every important factual claim should have one or more "
            "supporting sources.\n\n"

            "For every source provide:\n"
            "- title\n"
            "- URL\n"
            "- publisher\n"
            "- relevance\n"
            "- source quality tier\n"
            "- source type\n\n"

            "Use these source tiers:\n"
            "Tier 1 = government, university, academic research, "
            "or established museum.\n"
            "Tier 2 = reputable journalism or established "
            "educational publications.\n"
            "Tier 3 = general websites, specialist blogs, "
            "or less authoritative publications.\n"
            "Tier 4 = Wikipedia, forums, social media, "
            "or other low-authority sources.\n\n"

            "Use source IDs for internal references. "
            "The application will normalize these IDs later.\n\n"

            "Prioritize accuracy over quantity.\n\n"

            "The research should be useful for an approximately "
            "8-minute educational YouTube video."
        )

    @staticmethod
    def _normalize_source_ids(
        research: Research,
    ) -> Research:
        """
        Normalize source IDs and all fact references.

        The AI may return URLs as source IDs. The application
        converts them into stable source_001, source_002, etc.
        """

        id_mapping: dict[str, str] = {}

        for index, source in enumerate(
            research.sources,
            start=1,
        ):
            old_id = source.id
            new_id = f"source_{index:03d}"

            id_mapping[old_id] = new_id

            source.id = new_id

        # Update references in key facts
        for fact in research.key_facts:
            fact.sources = [
                id_mapping.get(source_id, source_id)
                for source_id in fact.sources
            ]

        # Update historical context
        for context in research.historical_context:
            context.sources = [
                id_mapping.get(source_id, source_id)
                for source_id in context.sources
            ]

        # Update myths
        for myth in research.common_myths:
            myth.sources = [
                id_mapping.get(source_id, source_id)
                for source_id in myth.sources
            ]

        # Update surprising facts
        for fact in research.surprising_facts:
            fact.sources = [
                id_mapping.get(source_id, source_id)
                for source_id in fact.sources
            ]

        return research

    @staticmethod
    def _save_research(
        research_file: Path,
        research: Research,
    ) -> None:
        """Save research as formatted JSON."""

        research_file.write_text(
            research.model_dump_json(indent=4),
            encoding="utf-8",
        )

    @staticmethod
    def _load_research(
        research_file: Path,
    ) -> Research:
        """Load and validate cached research."""

        data = json.loads(
            research_file.read_text(
                encoding="utf-8"
            )
        )

        return Research.model_validate(data)