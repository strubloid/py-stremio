"""TorrentsDB – Torrentio fork scraping 1337x, TPB, YTS, EZTV, RARBG, Zooqle, etc."""

from ...base import HttpAddon


class TorrentsDBAddon(HttpAddon):
    """TorrentsDB – a Torrentio fork with an expanded provider pool."""

    name = "TorrentsDB"
    base_url = "https://torrentsdb.com"

    def get_url(self, api_key: str | None = None) -> str:
        if api_key:
            return f"{self.base_url}/realdebrid={api_key}/"
        return self.base_url
