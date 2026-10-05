from typing import Any, Protocol, TypedDict

from modules.topic_intelligence.models import (
    OpportunityCandidate,
    TopicDiscoveryRequest,
)


class TopicProvider(Protocol):
    name: str

    def discover(self, request: TopicDiscoveryRequest) -> list[OpportunityCandidate]:
        """Return provider-backed candidate topics; never fabricate metrics."""
        ...


class TopicDemandEnrichment(TypedDict):
    available: bool
    metrics: dict[str, dict[str, Any]]
    related_keywords: list[str]
    query: str
    raw_response: Any
    operation: dict[str, str]


class ProviderUnavailableError(RuntimeError):
    """Raised when live discovery cannot run with the current configuration."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "PROVIDER_UNAVAILABLE",
        tool: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.tool = tool
