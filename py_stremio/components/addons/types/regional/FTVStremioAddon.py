"""FTV Stremio – French television catch-up and streaming."""

from ...base import HttpAddon


class FTVStremioAddon(HttpAddon):
    """FTV Stremio – French television catch-up and streaming."""

    name = "FTVStremio"
    base_url = "https://ftv-stremio.surge.sh"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url