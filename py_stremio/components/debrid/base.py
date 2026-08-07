"""Base debrid provider interface and registry."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class DebridProviderInfo:
    name: str
    display_name: str
    api_key_env_var: str
    is_configured: bool
    is_available: bool


class BaseDebridProvider(ABC):
    """Abstract base class for debrid service providers.

    All debrid providers must implement:
    - resolve_torrent(): Take an info_hash and optionally a file index,
                         return a direct download URL or None.
    - resolve_link(): Take a hoster/premium link URL, return resolved URL or None.
    - is_available(): Check if this provider is configured and working.
    - get_name(): Return the provider's identifier.
    """

    name: ClassVar[str] = "base"
    display_name: ClassVar[str] = "Base Provider"
    api_key_env_var: ClassVar[str] = ""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    @abstractmethod
    def resolve_torrent(self, info_hash: str, file_idx: int | None = None) -> str | None:
        """Resolve torrent via this debrid service.

        Args:
            info_hash: The torrent info hash (40 char hex string).
            file_idx: Optional zero-based file index to select specific file.

        Returns:
            Direct download URL if successful, None otherwise.
        """
        pass

    @abstractmethod
    def resolve_link(self, url: str) -> str | None:
        """Resolve a premium link/hoster URL through this debrid service.

        Args:
            url: The premium/hoster URL to resolve.

        Returns:
            Resolved direct URL if successful, None otherwise.
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this debrid service is configured and available.

        Returns:
            True if configured and responding, False otherwise.
        """
        pass

    def get_name(self) -> str:
        """Return the provider's identifier."""
        return self.name

    def get_info(self) -> DebridProviderInfo:
        """Get provider info for display."""
        return DebridProviderInfo(
            name=self.name,
            display_name=self.display_name,
            api_key_env_var=self.api_key_env_var,
            is_configured=bool(self.api_key),
            is_available=self.is_available(),
        )


_PROVIDERS: dict[str, type[BaseDebridProvider]] = {}


def register_debrid_provider(provider_class: type[BaseDebridProvider]) -> None:
    """Register a debrid provider class."""
    _PROVIDERS[provider_class.name] = provider_class


def get_debrid_provider(name: str) -> BaseDebridProvider | None:
    """Get a debrid provider instance by name."""
    provider_class = _PROVIDERS.get(name)
    if provider_class is None:
        return None
    return provider_class()


def get_all_provider_names() -> list[str]:
    """Get names of all registered providers."""
    return list(_PROVIDERS.keys())


def create_all_providers() -> list[BaseDebridProvider]:
    """Create instances of all registered providers."""
    return [cls() for cls in _PROVIDERS.values()]
