"""Animes Season – seasonal anime tracker with stream links."""

from ...base import HttpAddon


class AnimesSeasonAddon(HttpAddon):
    """Animes Season – seasonal anime tracker with stream links."""

    name = "AnimesSeason"
    base_url = "https://victorgveloso.github.io/animes-season-addon"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url