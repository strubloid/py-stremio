"""Ytztvio – wraps YTS movie and EZTV show torrent APIs."""

from ...base import HttpAddon


class YtztvioAddon(HttpAddon):
    """Ytztvio – lightweight addon wrapping YTS and EZTV APIs for torrent streams."""

    name = "Ytztvio"
    base_url = "https://ytztvio.galacticcapsule.workers.dev"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
