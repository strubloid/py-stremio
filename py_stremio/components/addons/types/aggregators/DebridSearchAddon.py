"""Debrid Search – search cached content across debrid services."""

from ...base import HttpAddon


class DebridSearchAddon(HttpAddon):
    """Debrid Search – search cached content across debrid services."""

    name = "DebridSearch"
    base_url = "https://68d69db7dc40-debrid-search.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url