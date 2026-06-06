"""Skyflix – free IPTV channels."""

from ...base import HttpAddon


class SkyflixAddon(HttpAddon):
    """Skyflix – free IPTV channels."""

    name = "Skyflix"
    base_url = "https://skyflix.onrender.com"
    enabled = False

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url