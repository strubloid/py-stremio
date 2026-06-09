"""SUPREME – multi-source torrent aggregator with debrid support."""
from ...base import HttpAddon


class SupremeAddon(HttpAddon):
    """SUPREME – streams from YTS, EZTV, TorrentGalaxy, NyaaSi, Knaben and more. Supports all major debrid services."""

    name = "SUPREME"
    base_url = "https://sup-sooty-one.vercel.app"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
