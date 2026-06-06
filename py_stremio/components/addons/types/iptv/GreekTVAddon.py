"""Stremio Greek TV – free Greek television channels."""

from ...base import HttpAddon


class GreekTVAddon(HttpAddon):
    """Stremio Greek TV – free Greek television channels."""

    name = "GreekTV"
    base_url = "https://stremio-greek-tv-latest.onrender.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url