"""Anime Kitsu – metadata + stream links for anime."""

from ...base import HttpAddon


class AnimeKitsuAddon(HttpAddon):
    """Anime Kitsu – metadata + stream links for anime."""

    name = "Anime-Kitsu"
    base_url = "https://anime-kitsu.strem.fun"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url