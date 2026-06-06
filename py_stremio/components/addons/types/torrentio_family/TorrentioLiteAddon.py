"""Torrentio Lite – same scrapers, simpler UI output."""

from .TorrentioAddon import TorrentioAddon


class TorrentioLiteAddon(TorrentioAddon):
    """Torrentio Lite – same scrapers, simpler UI output."""

    name = "Torrentio-Lite"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/lite|realdebrid={api_key}/"
        return f"{self.base_url}/lite/"