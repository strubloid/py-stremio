"""Base addon abstractions and reusable HTTP behavior."""
from abc import ABC, abstractmethod

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
                timeout=15,
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
            )
            for stream in streams_data
        ]


class HttpAddon(BaseAddon):
    """Reusable addon implementation for standard Stremio stream endpoints."""

    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        url = self.query_stream_url(type_, id_)
        streams_data = self.fetch_streams(url)
        return self.parse_streams(streams_data)


class UrlAddon(HttpAddon):
    """Generic addon backed by a configured URL."""

    def __init__(self, url: str):
        self._base_url = url.rstrip("/").replace("/manifest.json", "")
        self.name = self._name_from_url(self._base_url)

    def get_url(self, api_key: str | None = None) -> str:
        return self._base_url

    @staticmethod
    def _name_from_url(url: str) -> str:
        parts = url.split("/")
        for part in reversed(parts):
            if part and not part.startswith("http") and not part.startswith("?"):
                return part[:30]
        return parts[-2][:30] if len(parts) > 1 else "UrlAddon"
