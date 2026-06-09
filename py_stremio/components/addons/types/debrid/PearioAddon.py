"""Peario – Watch movies with friends in sync."""
from ...base import HttpAddon


class PearioAddon(HttpAddon):
    """Peario – synchronized watch party streaming addon."""

    name = "Peario"
    base_url = "https://addon.peario.xyz"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
