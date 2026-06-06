"""Nucleus – feature-rich scraper with Clamor integration."""

from ...base import HttpAddon


class NucleusAddon(HttpAddon):
    """Nucleus – feature-rich scraper with Clamor integration."""

    name = "Nucleus"
    base_url = "https://nucleus.stremio.tech"
    enabled = False

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url