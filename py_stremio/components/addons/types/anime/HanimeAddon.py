"""Hanime – hentai anime streams."""

from ...base import HttpAddon


class HanimeAddon(HttpAddon):
    """Hanime – hentai anime streams."""

    name = "Hanime"
    base_url = "https://86f0740f37f6-hanime-stremio.baby-beamup.club"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url