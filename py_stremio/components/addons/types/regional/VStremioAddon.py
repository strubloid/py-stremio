"""VStremio – Vietnamese-language movies and shows."""

from ...base import HttpAddon


class VStremioAddon(HttpAddon):
    """VStremio – Vietnamese-language movies and shows."""

    name = "VStremio"
    base_url = "https://vstremio.vercel.app"
    enabled = False

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url