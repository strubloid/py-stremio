"""Torrentio with Portuguese language filter."""

from .TorrentioAddon import TorrentioAddon


class TorrentioPortugueseAddon(TorrentioAddon):
    """Torrentio with Portuguese language filter."""

    name = "Torrentio-PT"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/language=portuguese|realdebrid={api_key}/"
        return self.base_url