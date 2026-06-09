"""KOD – 29 torrent sources aggregator with debrid support."""
from ...base import HttpAddon


class KodAddon(HttpAddon):
    """KOD – torrent streams from 29 sources, sorted by seeders. Supports all debrid services."""

    name = "KOD"
    base_url = "https://kod-three.vercel.app"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
