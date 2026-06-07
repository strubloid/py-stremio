"""StreamViX – multi-provider HTTP stream addon with proxy support."""

from ...base import HttpAddon


class StreamViXAddon(HttpAddon):
    """StreamViX | ElfHosted – multi-provider aggregator with proxy support."""

    name = "StreamViX"
    base_url = "https://streamvix.hayd.uk"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
