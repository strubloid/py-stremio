"""Manager for searching registered Stremio addons."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from .base import BaseAddon, UrlAddon
from .builtin import (
    AnimeKitsuAddon,
    BrazucaTorrentsAddon,
    CometAddon,
    HDHubAddon,
    MediaFusionAddon,
    ThePirateBayPlusAddon,
    TorrentioAddon,
    TorrentioPortugueseAddon,
    TorrentioSortSeedersAddon,
)
from .models import StreamInfo

SEARCH_CONCURRENCY = 10  # max parallel addon queries


def _addon_url(addon: BaseAddon) -> str:
    """Return the clean addon URL to remember in configs.

    Runtime get_url(api_key) may embed RealDebrid keys or base64 configs.  Those
    URLs are only for requests; persisted server caches must stay clean so the
    key continues to live in .env only.
    """
    try:
        return addon.get_url(None)
    except TypeError:
        return addon.get_url()


class AddonManager:
    """Manager to handle multiple addons."""

    def __init__(self):
        self.addons: list[BaseAddon] = []

    def register(self, addon: BaseAddon):
        """Register an addon unless it has been disabled."""
        if not getattr(addon, "enabled", True):
            return
        self.addons.append(addon)

    def register_url(self, url: str):
        """Register an addon from URL."""
        self.addons.append(UrlAddon(url))

    def search_all(self, type_: str, id_: str, max_addons: int = 3) -> list[StreamInfo]:
        """Search registered addons for streams (stops at first success)."""
        for addon in self.addons[:max_addons]:
            chunks = self._try_addon(addon, type_, id_)
            if chunks:
                return chunks
        return []

    def search_all_addons_and_collect_working(
        self, type_: str, id_: str
    ) -> tuple[list[StreamInfo], list[str]]:
        """Search ALL addons concurrently and return streams + working addon URLs."""
        import itertools
        import sys

        if not self.addons:
            return [], []

        total = len(self.addons)
        spinner = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
        done_count = 0

        print(f"    Searching {total} addons...", end="", flush=True)
        working_addon_urls: list[str] = []
        all_streams: list[StreamInfo] = []
        result_lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=SEARCH_CONCURRENCY) as executor:
            futures = {
                executor.submit(self._try_addon, addon, type_, id_): addon
                for addon in self.addons
            }
            for future in as_completed(futures):
                done_count += 1
                char = next(spinner)
                sys.stdout.write(f"\r    {char} Searching addons ({done_count}/{total})")
                sys.stdout.flush()

                addon = futures[future]
                try:
                    streams = future.result(timeout=20)
                except Exception as exc:
                    from ..error_logger import log_error

                    log_error(
                        f"addon_timeout({addon.name})",
                        exc,
                        f"{type_}/{id_}",
                    )
                    streams = []
                if streams:
                    with result_lock:
                        addon_url = _addon_url(addon)
                        for stream in streams:
                            stream.addon_url = stream.addon_url or addon_url
                        all_streams.extend(streams)
                        if addon_url and addon_url not in working_addon_urls:
                            working_addon_urls.append(addon_url)

        # Clear spinner line
        print()

        return all_streams, working_addon_urls

    def _try_addon(self, addon: BaseAddon, type_: str, id_: str) -> list[StreamInfo]:
        """Query one addon — returns streams or empty list."""
        try:
            return addon.get_streams(type_, id_)
        except Exception as exc:
            from ..error_logger import log_error

            log_error(f"try_addon({addon.name})", exc, f"{type_}/{id_}")
            return []

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
