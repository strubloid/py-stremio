"""CineTorrent – torrent-based stream provider."""

from ...base import HttpAddon


class CineTorrentAddon(HttpAddon):
    """CineTorrent – torrent-based stream provider."""

    name = "CineTorrent"
    base_url = "https://150203dd784e-cinetorrent-addon.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url