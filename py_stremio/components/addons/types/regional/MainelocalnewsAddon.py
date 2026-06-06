"""Maine Local News – local news streams."""

from ...base import HttpAddon


class MainelocalnewsAddon(HttpAddon):
    """Maine Local News – local news streams."""

    name = "MaineLocalNews"
    base_url = "https://a0da031547f5-stremio-mainelocalnews.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url