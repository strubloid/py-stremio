"""CIN – P2P torrent-based stream provider."""

from ...base import HttpAddon


class CinAddon(HttpAddon):
    """CIN – P2P torrent aggregator. Fast loading, high-quality playback options."""

    name = "CIN"
    base_url = "https://cinnn.vercel.app"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url