"""Orion – premium scraper with vast cached-stream database."""

from ...base import HttpAddon


class OrionAddon(HttpAddon):
    """Orion – premium scraper with vast cached-stream database."""

    name = "Orion"
    base_url = "https://5a0d1888fa64-orion.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url