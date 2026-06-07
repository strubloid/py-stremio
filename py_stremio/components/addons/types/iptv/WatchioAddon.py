"""Watchio.live TV – live TV streaming via HTTP."""

from ...base import HttpAddon


class WatchioAddon(HttpAddon):
    """Watchio.live TV – live TV channels and HTTP streams."""

    name = "Watchio.live TV"
    base_url = "https://watchio-addon.pages.dev"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
