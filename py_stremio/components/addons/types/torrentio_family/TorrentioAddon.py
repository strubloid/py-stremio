"""Torrentio family of addons — scrapes 1337x, TPB, RARBG, YTS, EZTV, etc."""

from ...base import HttpAddon


class TorrentioAddon(HttpAddon):
    """Torrentio – the most popular Stremio addon."""

    name = "Torrentio"
    base_url = "https://torrentio.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/realdebrid={api_key}/"
        return self.base_url