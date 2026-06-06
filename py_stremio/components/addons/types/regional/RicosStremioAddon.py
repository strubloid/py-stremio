"""Rico's Stremio – Spanish-language content addon."""

from ...base import HttpAddon


class RicosStremioAddon(HttpAddon):
    """Rico's Stremio – Spanish-language content addon."""

    name = "RicosStremio"
    base_url = "https://zoreu.github.io/ricosstremio"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url