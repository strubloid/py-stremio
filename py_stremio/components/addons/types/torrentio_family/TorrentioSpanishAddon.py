"""Torrentio with Spanish language filter."""

from .TorrentioAddon import TorrentioAddon


class TorrentioSpanishAddon(TorrentioAddon):
    """Torrentio with Spanish language filter."""

    name = "Torrentio-ES"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/language=spanish|realdebrid={api_key}/"
        return self.base_url