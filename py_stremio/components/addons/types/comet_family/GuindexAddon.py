"""Guindex – community-maintained index of cached debrid streams."""

from ...base import HttpAddon
from .GuindexAddonConfigurer import GuindexAddonConfigurer


class GuindexAddon(HttpAddon):
    """Guindex – community-maintained index of cached debrid streams."""

    name = "Guindex"
    base_url = "https://guindex-stremio.vercel.app"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return GuindexAddonConfigurer().configure(self.base_url, api_key)
        return self.base_url