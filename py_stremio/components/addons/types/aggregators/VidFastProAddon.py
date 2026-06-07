"""VidFast Pro – HTTP stream addon for movies and TV shows."""

from ...base import HttpAddon


class VidFastProAddon(HttpAddon):
    """VidFast Pro – simple HTTP streaming addon for movies and series."""

    name = "VidFast Pro"
    base_url = "https://vidfast-stremio-addon.zmoualhi.workers.dev"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
