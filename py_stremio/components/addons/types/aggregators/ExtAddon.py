"""Ext – multi-source stream aggregator with a torrent / hoster mix."""

from ...base import HttpAddon


class ExtAddon(HttpAddon):
    """Ext – ext.to stream aggregator. Scraper-style, mixes hosted and
    debrid-capable sources behind a single manifest. Known to be
    Cloudflare-protected from many networks; the cloudscraper/httpx
    client retries with a Chrome UA so most home connections reach
    the manifest.

    The site is reachable at ``https://ext.to/manifest.json`` and
    powers a public Stremio catalog (``/browse``) that shows
    torrent results for shows like *90 Day Fiance: The Other Way*.
    """

    name = "Ext"
    base_url = "https://ext.to"

    def get_url(self, api_key: str | None = None) -> str:
        return self.base_url
