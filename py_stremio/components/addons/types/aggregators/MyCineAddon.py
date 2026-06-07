"""MY CINE – movie and series streaming addon."""

from ...base import HttpAddon


class MyCineAddon(HttpAddon):
    """MY CINE – streams movies and TV series."""

    name = "MY CINE"
    base_url = "https://mycine.alwaysdata.net"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
