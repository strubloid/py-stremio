"""Consumet – multi-source anime and movie API."""

from ...base import HttpAddon


class ConsumetAddon(HttpAddon):
    """Consumet – multi-source anime and movie API."""

    name = "Consumet"
    base_url = "https://b89262c192b0-stremio-consumet-addon.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url