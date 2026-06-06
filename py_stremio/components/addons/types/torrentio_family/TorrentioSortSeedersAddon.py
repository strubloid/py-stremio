"""Torrentio sorted by seeders."""

from .TorrentioAddon import TorrentioAddon


class TorrentioSortSeedersAddon(TorrentioAddon):
    """Torrentio sorted by seeders."""

    name = "Torrentio-SortSeeders"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/sort=seeders|realdebrid={api_key}/"
        return self.base_url