"""Torrentio with Italian language filter."""

from .TorrentioAddon import TorrentioAddon


class TorrentioItalianAddon(TorrentioAddon):
    """Torrentio configured to return Italian and Italian-compatible releases."""

    name = "Torrentio-IT"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/language=italian|realdebrid={api_key}/"
        return f"{self.base_url}/language=italian/"
