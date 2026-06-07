"""NebulaStreams – multi-provider HTTP stream addon for movies and series."""

from ...base import HttpAddon


class NebulaStreamsAddon(HttpAddon):
    """NebulaStreams – fast multi-provider HTTP stream addon with configurable instances."""

    name = "NebulaStreams"
    base_url = "https://nebulastreams.onrender.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
