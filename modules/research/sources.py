from modules.research.models import (
    Source,
    SourceTier,
    SourceType,
)


class SourceManager:
    """Manages research sources for a video project."""

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}

    def add_source(
        self,
        title: str,
        url: str,
        publisher: str,
        relevance: str,
        tier: SourceTier = "4",
        source_type: SourceType = "other",
    ) -> Source:
        """Add a source and return the created Source object."""

        source_id = self._generate_source_id()

        source = Source(
            id=source_id,
            title=title,
            url=url,
            publisher=publisher,
            relevance=relevance,
            tier=tier,
            source_type=source_type,
        )

        self._sources[source_id] = source

        return source

    def get_source(self, source_id: str) -> Source:
        """Return a source by ID."""

        if source_id not in self._sources:
            raise KeyError(f"Source not found: {source_id}")

        return self._sources[source_id]

    def get_all_sources(self) -> list[Source]:
        """Return all registered sources."""

        return list(self._sources.values())

    def _generate_source_id(self) -> str:
        """Generate a sequential source ID."""

        number = len(self._sources) + 1

        return f"source_{number}"