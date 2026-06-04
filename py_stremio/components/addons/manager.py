"""Manager for searching registered Stremio addons."""
from .base import BaseAddon, UrlAddon
from .builtin import (
    AnimeKitsuAddon,
    BrazucaTorrentsAddon,
    CustomCometAddon,
    HDHubAddon,
    MediaFusionAddon,
    ThePirateBayPlusAddon,
    TorrentioAddon,
    TorrentioPortugueseAddon,
    TorrentioSortSeedersAddon,
)
from .models import StreamInfo


def _addon_url(addon: BaseAddon) -> str:
    try:
        return addon.get_url(getattr(addon, "api_key", None))
    except TypeError:
        return addon.get_url()


class AddonManager:
    """Manager to handle multiple addons."""

    def __init__(self):
        self.addons: list[BaseAddon] = []

    def register(self, addon: BaseAddon):
        """Register an addon."""
        self.addons.append(addon)

    def register_url(self, url: str):
        """Register an addon from URL."""
        self.addons.append(UrlAddon(url))

    def search_all(self, type_: str, id_: str, max_addons: int = 3) -> list[StreamInfo]:
        """Search all registered addons for streams."""
        for addon in self.addons[:max_addons]:
            print(f"    Trying {addon.name}...")
            streams = addon.get_streams(type_, id_)
            if streams:
                print(f"    ✓ Found {len(streams)} streams from {addon.name}")
                return streams
        return []

    def search_all_addons_and_collect_working(
        self, type_: str, id_: str
    ) -> tuple[list[StreamInfo], list[str]]:
        """Search ALL addons and return streams + list of working addon URLs."""
        working_addon_urls = []
        all_streams = []

        for addon in self.addons:
            print(f"    Trying {addon.name}...")
            streams = addon.get_streams(type_, id_)
            if streams:
                print(f"    ✓ Found {len(streams)} streams from {addon.name}")
                all_streams.extend(streams)
                addon_url = _addon_url(addon)
                if addon_url and addon_url not in working_addon_urls:
                    working_addon_urls.append(addon_url)

        return all_streams, working_addon_urls

    def search_until_found(self, type_: str, id_: str) -> list[StreamInfo]:
        """Search addons until streams are found."""
        return self.search_all(type_, id_, max_addons=len(self.addons))


def load_addons_from_file(filepath: str = "addons.txt") -> list[str]:
    """Load addon URLs from file."""
    from .factory import load_addons_from_file as load
    return load(filepath)


def create_addon_manager() -> AddonManager:
    """Create and configure addon manager with all available addons."""
    from .factory import create_addon_manager as create
    return create()


def search_addons(type_: str, id_: str, max_addons: int = 3) -> list[StreamInfo]:
    """Search all addons for streams."""
    from .factory import search_addons as search
    return search(type_, id_, max_addons)


def create_addon_manager_from_urls(urls: list[str]) -> AddonManager:
    """Create addon manager from specific URLs."""
    from .factory import create_addon_manager_from_urls as create
    return create(urls)
