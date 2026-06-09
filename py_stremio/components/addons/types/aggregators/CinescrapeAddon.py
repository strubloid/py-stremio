"""Cinescrape – multi-source HTTPS streaming addon."""
from ...base import HttpAddon


class CinescrapeAddon(HttpAddon):
    """Cinescrape – scrapes publicly available sources for fast HTTPS streams."""

    name = "Cinescrape"
    base_url = "https://bc48e59c61df-cinescrape-docker.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
