"""Torrentio with Hindi language filter."""

from .TorrentioAddon import TorrentioAddon


class TorrentioHindiAddon(TorrentioAddon):
    """Torrentio with Hindi language filter."""

    name = "Torrentio-HI"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/language=hindi|realdebrid={api_key}/"
        return self.base_url