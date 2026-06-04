"""Addon manager construction helpers."""
from urllib.parse import unquote

from ..settings import settings
from .base import UrlAddon
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
from .manager import AddonManager
from .models import StreamInfo


def load_addons_from_file(filepath: str = "addons.txt") -> list[str]:
    """Load addon URLs from file."""
    try:
        with open(filepath, "r") as f:
            return [unquote(line.strip()) for line in f if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        return []


def _register_file_addons(manager: AddonManager, addon_urls: list[str]) -> None:
    for url in addon_urls:
        try:
            manager.register(UrlAddon(url))
        except Exception:
            pass


def _register_builtin_addons(manager: AddonManager, api_key: str | None) -> None:
    manager.register(TorrentioAddon())
    manager.register(TorrentioSortSeedersAddon())
    manager.register(MediaFusionAddon())
    manager.register(AnimeKitsuAddon())
    manager.register(BrazucaTorrentsAddon())
    manager.register(ThePirateBayPlusAddon())
    manager.register(HDHubAddon())
    manager.register(CustomCometAddon())

    if api_key:
        manager.register(TorrentioPortugueseAddon())


def _apply_api_key(manager: AddonManager, api_key: str | None) -> None:
    for addon in manager.addons:
        addon.api_key = api_key


def create_addon_manager() -> AddonManager:
    """Create and configure addon manager with all available addons."""
    api_key = settings.REAL_DEBRID_API_KEY
    manager = AddonManager()
    addon_urls = load_addons_from_file("addons.txt")

    if addon_urls:
        print(f"    Loading {len(addon_urls)} addons from addons.txt...")
        _register_file_addons(manager, addon_urls)
    else:
        _register_builtin_addons(manager, api_key)

    _apply_api_key(manager, api_key)
    return manager


def create_addon_manager_from_urls(urls: list[str]) -> AddonManager:
    """Create addon manager from specific URLs."""
    manager = AddonManager()
    api_key = settings.REAL_DEBRID_API_KEY

    for url in urls:
        try:
            addon = UrlAddon(url)
            addon.api_key = api_key
            manager.register(addon)
        except Exception:
            pass

    return manager


def search_addons(type_: str, id_: str, max_addons: int = 3) -> list[StreamInfo]:
    """Search all addons for streams."""
    manager = create_addon_manager()
    return manager.search_all(type_, id_, max_addons)
