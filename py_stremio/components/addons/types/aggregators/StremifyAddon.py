"""Stremify – multi-scraper addon hosted on ElfHosted."""

from ...base import HttpAddon


class StremifyAddon(HttpAddon):
    """Stremify – multi-scraper addon hosted on ElfHosted."""

    name = "Stremify"
    base_url = "https://stremify.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url