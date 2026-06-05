"""Base interface for host-specific addon URL configuration."""

from abc import ABC, abstractmethod


class AddonUrlConfigurer(ABC):
    """Build the runtime URL for an addon loaded from a clean saved URL."""

    host_match: str = ""
    enabled: bool = True

    def matches(self, url: str) -> bool:
        """Return True when this configurer should handle *url*."""
        return self.host_match in url

    @abstractmethod
    def configure(self, base_url: str, api_key: str) -> str:
        """Return the runtime URL, with any required RD config injected."""
