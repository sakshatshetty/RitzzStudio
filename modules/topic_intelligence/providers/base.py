from typing import Protocol

from modules.topic_intelligence.models import (
    OpportunityCandidate,
    TopicDiscoveryRequest,
)


class TopicProvider(Protocol):
    name: str

    def discover(self, request: TopicDiscoveryRequest) -> list[OpportunityCandidate]:
        """Return provider-backed candidate topics; never fabricate metrics."""


class ProviderUnavailableError(RuntimeError):
    """Raised when live discovery cannot run with the current configuration."""
