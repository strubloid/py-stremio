"""Guindex URL configuration."""

import re
from urllib.parse import urlparse

from .addon_url_configurer import AddonUrlConfigurer


class GuindexAddonConfigurer(AddonUrlConfigurer):
    """Inject RealDebrid into clean Guindex URLs."""

    host_match = "guindex-stremio.vercel.app"

    def configure(self, base_url: str, api_key: str) -> str:
        parsed = urlparse(base_url.rstrip("/"))
        clean_path = re.sub(r"/realdebrid/[^/]+", "", parsed.path).rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{clean_path}/realdebrid/{api_key}/"
