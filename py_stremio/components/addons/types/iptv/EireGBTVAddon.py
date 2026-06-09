"""EIRE + GB TV – Irish and British IPTV channels."""
from ...base import HttpAddon


class EireGBTVAddon(HttpAddon):
    """EIRE + GB TV – Irish and British IPTV streaming channels."""

    name = "EIRE + GB TV"
    base_url = "https://heiregby.surge.sh"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
