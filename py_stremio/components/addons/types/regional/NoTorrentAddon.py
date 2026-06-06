"""NoTorrent – lightweight torrent stream provider."""

from ...base import HttpAddon


class NoTorrentAddon(HttpAddon):
    """NoTorrent – lightweight torrent stream provider."""

    name = "NoTorrent"
    base_url = "https://addon.notorrent2.workers.dev"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url