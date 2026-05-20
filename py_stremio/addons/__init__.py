"""Addons package - Multi-addon support for finding streams."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import httpx

from ..settings import settings


@dataclass
class StreamInfo:
    name: str
    url: str | None = None
    info_hash: str | None = None
    file_idx: int | None = None
    title: str | None = None
    addon_name: str = ""


class BaseAddon(ABC):
    """Base class for all Stremio addons."""

    name: str = "BaseAddon"
    base_url: str = ""
    api_key: str | None = None

    @abstractmethod
    def get_url(self, api_key: str | None = None) -> str:
        """Get the configured addon URL."""
        pass

    @abstractmethod
    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        """Query addon for streams."""
        pass

    def query_stream_url(self, type_: str, id_: str) -> str:
        return f"{self.get_url(self.api_key).rstrip('/')}/stream/{type_}/{id_}.json"
        """Build the stream query URL."""
        return f"{self.get_url().rstrip('/')}/stream/{type_}/{id_}.json"

    def fetch_streams(self, url: str) -> list[dict]:
        """Fetch streams from URL."""
        try:
            response = httpx.get(
                url,
                timeout=15,
                headers={"User-Agent": "Stremio/4.4.168", "Accept": "application/json"}
            )
            response.raise_for_status()
            return response.json().get("streams", [])
        except Exception:
            return []

    def parse_streams(self, streams_data: list[dict]) -> list[StreamInfo]:
        """Parse stream data into StreamInfo objects."""
        return [
            StreamInfo(
                name=s.get("name", "unknown"),
                url=s.get("url"),
                info_hash=s.get("infoHash"),
                file_idx=s.get("fileIdx"),
                title=s.get("title"),
                addon_name=self.name
            )
            for s in streams_data
        ]


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
                addon_url = addon.get_url()
                if addon_url and addon_url not in working_addon_urls:
                    working_addon_urls.append(addon_url)

        return all_streams, working_addon_urls

    def search_until_found(self, type_: str, id_: str) -> list[StreamInfo]:
        """Search addons until streams are found."""
        return self.search_all(type_, id_, max_addons=len(self.addons))


class TorrentioAddon(BaseAddon):
    """Torrentio addon with RealDebrid support."""

    name = "Torrentio"
    base_url = "https://torrentio.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/realdebrid={api_key}/"
        return self.base_url

    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        url = self.query_stream_url(type_, id_)
        streams_data = self.fetch_streams(url)
        return self.parse_streams(streams_data)


class TorrentioSortSeedersAddon(TorrentioAddon):
    """Torrentio sorted by seeders."""

    name = "Torrentio-SortSeeders"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/sort=seeders|realdebrid={api_key}/"
        return self.base_url


class TorrentioPortugueseAddon(TorrentioAddon):
    """Torrentio with Portuguese language filter."""

    name = "Torrentio-PT"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/language=portuguese|realdebrid={api_key}/"
        return self.base_url


class MediaFusionAddon(BaseAddon):
    """MediaFusion ElfHosted addon."""

    name = "MediaFusion"
    base_url = "https://mediafusion.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url

    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        url = self.query_stream_url(type_, id_)
        streams_data = self.fetch_streams(url)
        return self.parse_streams(streams_data)


class AnimeKitsuAddon(BaseAddon):
    """Anime Kitsu metadata addon."""

    name = "Anime-Kitsu"
    base_url = "https://anime-kitsu.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url

    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        url = self.query_stream_url(type_, id_)
        streams_data = self.fetch_streams(url)
        return self.parse_streams(streams_data)


class BrazucaTorrentsAddon(BaseAddon):
    """Brazuca Torrents - Brazilian content."""

    name = "Brazuca-Torrents"
    base_url = "https://94c8cb9f702d-brazuca-torrents.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/sort=size|realdebrid={api_key}/"
        return self.base_url

    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        url = self.query_stream_url(type_, id_)
        streams_data = self.fetch_streams(url)
        return self.parse_streams(streams_data)


class ThePirateBayPlusAddon(BaseAddon):
    """ThePirateBay+ addon."""

    name = "ThePirateBay+"
    base_url = "https://thepiratebay-plus.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url

    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        url = self.query_stream_url(type_, id_)
        streams_data = self.fetch_streams(url)
        return self.parse_streams(streams_data)


class CustomCometAddon(BaseAddon):
    """Comet addon - debrid support."""

    name = "Comet"
    base_url = "https://comet.feels.legal"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            config = "eyJtYXhSZXN1bHRzUGVyUmVzb2x1dGlvbiI6MCwibWF4U2l6ZSI6MCwiY2FjaGVkT25seSI6ZmFsc2UsInNvcnRDYWNoZWRVbmNhY2hlZFRvZ2V0aGVyIjpmYWxzZSwicmVtb3ZlVHJhc2giOnRydWUsInJlc3VsdEZvcm1hdCI6WyJhbGwiXSwiZGVicmlkU2VydmljZXMiOlt7InNlcnZpY2UiOiJyZWFsZGVicmlkIiwiYXBpS2V5IjoiUlVNMktTVVhZWjRSUjVYWTM0UzNIS0pDNEwzT0g2TzI2VE1DRk82SUlIQlNGWlZLVDdBQSJ9XSwiZW5hYmxlVG9ycmVudCI6ZmFsc2UsImRlZHVwbGljYXRlU3RyZWFtcyI6ZmFsc2UsInNjcmFwZURlYnJpZEFjY291bnRUb3JyZW50cyI6ZmFsc2UsImRlYnJpZFN0cmVhbVByb3h5UGFzc3dvcmQiOiIiLCJsYW5ndWFnZXMiOnsicmVxdWlyZWQiOltdLCJhbGxvd2VkIjpbXSwiZXhjbHVkZSI6W10sInByZWZlcnJlZCI6W119LCJyZXNvbHV0aW9ucyI6e30sIm9wdGlvbnMiOnsicmVtb3ZlX3JhbmtzX3VuZGVyIjotMTAwMDAwMDAwMDAsImFsbG93X2VuZ2xpc2hfaW5fbGFuZ3VhZ2VzIjpmYWxzZSwicmVtb3ZlX3Vua25vd25fbGFuZ3VhZ2VzIjpmYWxzZX19"
            return f"{self.base_url}/{config}/manifest.json"
        return self.base_url

    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        url = self.query_stream_url(type_, id_)
        streams_data = self.fetch_streams(url)
        return self.parse_streams(streams_data)


class HDHubAddon(BaseAddon):
    """HDHub addon."""

    name = "HDHub"
    base_url = "https://hdhub.thevolecitor.qzz.io"

    def get_url(self, api_key: str | None = None) -> str:
        config = "eyJ0b3Jib3giOiJ1bnNldCIsInF1YWxpdGllcyI6IjIxNjBwLDEwODBwLDcyMHAiLCJzb3J0IjoiZGVzYyJ9"
        return f"{self.base_url}/{config}/manifest.json"

    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        url = self.query_stream_url(type_, id_)
        streams_data = self.fetch_streams(url)
        return self.parse_streams(streams_data)


class UrlAddon(BaseAddon):
    """Generic addon from URL."""

    def __init__(self, url: str):
        self._base_url = url.rstrip('/').replace('/manifest.json', '')
        # Extract a clean name from the URL
        parts = self._base_url.split('/')
        for part in reversed(parts):
            if part and not part.startswith('http') and not part.startswith('?'):
                self.name = part[:30]
                break
        else:
            self.name = parts[-2][:30] if len(parts) > 1 else "UrlAddon"

    def get_url(self, api_key: str | None = None) -> str:
        return self._base_url

    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        url = self.query_stream_url(type_, id_)
        streams_data = self.fetch_streams(url)
        return self.parse_streams(streams_data)


def load_addons_from_file(filepath: str = "addons.txt") -> list[str]:
    """Load addon URLs from file."""
    from urllib.parse import unquote
    try:
        with open(filepath, "r") as f:
            return [unquote(line.strip()) for line in f if line.strip() and not line.startswith("#")]
    except FileNotFoundError:
        return []


def create_addon_manager() -> AddonManager:
    """Create and configure addon manager with all available addons."""
    api_key = settings.REAL_DEBRID_API_KEY

    manager = AddonManager()

    # First try to load from addons.txt file
    addon_urls = load_addons_from_file("addons.txt")

    if addon_urls:
        print(f"    Loading {len(addon_urls)} addons from addons.txt...")
        for url in addon_urls:
            try:
                manager.register(UrlAddon(url))
            except Exception:
                pass
    else:
        # Fallback to built-in addons
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

    for addon in manager.addons:
        addon.api_key = api_key

    return manager


def search_addons(type_: str, id_: str, max_addons: int = 3) -> list[StreamInfo]:
    """Search all addons for streams."""
    manager = create_addon_manager()
    return manager.search_all(type_, id_, max_addons)


def create_addon_manager_from_urls(urls: list[str]) -> AddonManager:
    """Create addon manager from specific URLs (for working addons)."""
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