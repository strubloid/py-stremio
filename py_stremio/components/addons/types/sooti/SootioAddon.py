"""Sootio – multi-scraper debrid addon with URL-encoded JSON config."""

from ...base import HttpAddon
from ._sooti_build import build_sootio_url


class SootioAddon(HttpAddon):
    """Sootio – multi-scraper debrid addon with URL-encoded JSON config."""

    name = "Sootio"
    base_url = "https://sooti.info"

    def get_url(self, api_key: str | None = None) -> str:
        return build_sootio_url(self.base_url, api_key)
