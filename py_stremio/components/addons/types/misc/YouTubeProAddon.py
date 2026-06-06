"""YouTube PRO – browse and stream YouTube content inside Stremio."""

from ...base import HttpAddon


class YouTubeProAddon(HttpAddon):
    """YouTube PRO – browse and stream YouTube content inside Stremio."""

    name = "YouTubePRO"
    base_url = "https://youtubepro-macu.onrender.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url