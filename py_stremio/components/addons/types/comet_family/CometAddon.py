"""Comet – modern lightweight torrent scraper."""

from ...base import HttpAddon
from ._comet_build import build_comet_url


class CometAddon(HttpAddon):
    """Comet – modern lightweight torrent scraper."""

    name = "Comet"
    base_url = "https://comet.feels.legal"

    def get_url(self, api_key: str | None = None) -> str:
        return build_comet_url(self.base_url, api_key)