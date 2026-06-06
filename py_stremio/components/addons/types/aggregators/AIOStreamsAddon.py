"""AIOStreams – all-in-one stream aggregator."""

from ...base import HttpAddon


class AIOStreamsAddon(HttpAddon):
    """AIOStreams – all-in-one stream aggregator."""

    name = "AIOStreams"
    base_url = "https://aiostreams.elfhosted.com"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url