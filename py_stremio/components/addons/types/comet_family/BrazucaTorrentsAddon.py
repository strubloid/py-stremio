"""Brazuca Torrents – Brazilian Portuguese content."""

from ...base import HttpAddon


class BrazucaTorrentsAddon(HttpAddon):
    """Brazuca Torrents – Brazilian Portuguese content."""

    name = "Brazuca-Torrents"
    base_url = "https://94c8cb9f702d-brazuca-torrents.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/sort=size|realdebrid={api_key}/"
        return self.base_url