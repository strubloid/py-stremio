"""StremThru – multi-debrid proxy aggregator (RD, AD, PM, TB)."""

from ...base import HttpAddon
from .StremThruAddonConfigurer import StremThruAddonConfigurer


class StremThruAddon(HttpAddon):
    """StremThru – multi-debrid proxy aggregator (RD, AD, PM, TB)."""

    name = "StremThru"
    base_url = "https://stremthru.13377001.xyz/stremio/torz"
    enabled = False

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return StremThruAddonConfigurer().configure(self.base_url, api_key)
        return self.base_url