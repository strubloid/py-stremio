"""Animepahe – free anime streams from animepahe.com."""

from ...base import HttpAddon


class AnimepaheAddon(HttpAddon):
    """Animepahe – free anime streams from animepahe.com."""

    name = "Animepahe"
    base_url = "https://animepahe-addon.stremio.tech"
    enabled = False

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url