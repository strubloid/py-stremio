"""Peerflix – simple torrent scraper addon."""

from ...base import HttpAddon


class PeerflixAddon(HttpAddon):
    """Peerflix – simple torrent scraper addon."""

    name = "Peerflix"
    base_url = "https://peerflix.mov"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url