"""AnimeStream – general anime streaming addon, no account required."""

from ...base import HttpAddon


class AnimeStreamAddon(HttpAddon):
    """AnimeStream – free anime streaming with no account required."""

    name = "AnimeStream"
    base_url = "https://animestream-addon.keypop3750.workers.dev"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
