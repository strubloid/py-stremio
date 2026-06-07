"""Flix-Streams – full-featured addon with Usenet, Live TV, and 4K support."""

from ...base import HttpAddon


class FlixStreamsAddon(HttpAddon):
    """Flix-Streams – multi-source streams with Usenet, Live TV, and 4K."""

    name = "Flix-Streams"
    base_url = "https://flixnest.app/flix-streams"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
