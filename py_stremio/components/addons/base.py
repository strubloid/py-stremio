"""Base addon abstractions and reusable HTTP behavior."""
from abc import ABC, abstractmethod
from collections.abc import Callable

import httpx

from .models import StreamInfo


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
        """Build the stream query URL."""
        return f"{self.get_url(self.api_key).rstrip('/')}/stream/{type_}/{id_}.json"

    def fetch_streams(self, url: str) -> list[dict]:
        """Fetch raw streams from an addon URL."""
        try:
            response = httpx.get(
                url,
                timeout=8,
                headers={"User-Agent": "Stremio/4.4.168", "Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json().get("streams", [])
        except Exception:
            return []

    def parse_streams(self, streams_data: list[dict]) -> list[StreamInfo]:
        """Parse stream dictionaries into StreamInfo objects."""
        return [
            StreamInfo(
                name=stream.get("name", "unknown"),
                url=stream.get("url"),
                info_hash=stream.get("infoHash"),
                file_idx=stream.get("fileIdx"),
                title=stream.get("title"),
                addon_name=self.name,
                filename=(stream.get("behaviorHints") or {}).get("filename"),
            )
            for stream in streams_data
        ]


class HttpAddon(BaseAddon):
    """Reusable addon implementation for standard Stremio stream endpoints."""

    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        url = self.query_stream_url(type_, id_)
        streams_data = self.fetch_streams(url)
        return self.parse_streams(streams_data)


# ── RD injection registry for UrlAddon ──────────────────────────────────
# Maps a URL substring to an injector function(base_url, api_key) -> str.
# This lets addons loaded from addons.txt get the RD key injected at
# request time without baking the key into the file.
URL_RD_INJECTORS: dict[str, Callable[[str, str], str]] = {}


def register_rd_injector(url_match: str, injector: Callable[[str, str], str]) -> None:
    """Register a URL pattern for automatic RD key injection in UrlAddon.

    Args:
        url_match: Substring to match in the addon URL
                   (e.g. 'intell-debridsearch.nepiraw.com').
        injector: Callable(base_url, api_key) returning the injected URL.
    """
    URL_RD_INJECTORS[url_match] = injector


class UrlAddon(HttpAddon):
    """Generic addon backed by a configured URL from addons.txt or other sources.

    The RD key is injected at request time via `get_url(api_key)` when the
    URL matches a registered injection pattern — no key is stored in the file.
    """

    def __init__(self, url: str):
        self._base_url = url.rstrip("/").replace("/manifest.json", "")
        self.name = self._name_from_url(self._base_url)

    def get_url(self, api_key: str | None = None) -> str:
        if not api_key:
            return self._base_url

        url = self._base_url.rstrip("/")

        # Try registered RD injection patterns
        for match_str, injector in URL_RD_INJECTORS.items():
            if match_str in url:
                return injector(url, api_key)

        return self._base_url

    @staticmethod
    def _name_from_url(url: str) -> str:
        parts = url.split("/")
        for part in reversed(parts):
            if part and not part.startswith("http") and not part.startswith("?"):
                return part[:30]
        return parts[-2][:30] if len(parts) > 1 else "UrlAddon"


# ── Register RD injection patterns for known addons ─────────────────────
# These addons are not in the built-in set but can use RD when the key
# is injected at request time.  Built-in addons (Torrentio, Guindex, etc.)
# have their own get_url() methods and are registered in factory.py.

register_rd_injector(
    "intell-debridsearch.nepiraw.com",
    lambda url, key: f"{url}/realdebrid={key}/",
)

register_rd_injector(
    "nyaa-scraper-stremio-addon.nmtl.app",
    lambda url, key: f"{url}/source=nyaa&rd={key}&v=1.9.1/",
)
