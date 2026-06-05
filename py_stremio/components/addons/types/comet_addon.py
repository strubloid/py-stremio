"""Comet URL configuration."""

import base64
import json
from urllib.parse import urlparse

from .addon_url_configurer import AddonUrlConfigurer


class CometAddonConfigurer(AddonUrlConfigurer):
    """Build Comet base64 config URLs that return RealDebrid playback links."""

    host_match = "comet."

    def matches(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc in {"comet.feels.legal", "comet.elfhosted.com"}

    def configure(self, base_url: str, api_key: str) -> str:
        parsed_base = urlparse(base_url)
        if parsed_base.netloc in {"comet.feels.legal", "comet.elfhosted.com"}:
            base_url = f"{parsed_base.scheme}://{parsed_base.netloc}"
        config = {
            "maxResultsPerResolution": 0,
            "maxSize": 0,
            "cachedOnly": False,
            "sortCachedUncachedTogether": False,
            "removeTrash": True,
            "resultFormat": ["all"],
            "debridServices": [{"service": "realdebrid", "apiKey": api_key}],
            "enableTorrent": False,
            "deduplicateStreams": False,
            "scrapeDebridAccountTorrents": False,
            "debridStreamProxyPassword": "",
            "languages": {"required": [], "allowed": [], "exclude": [], "preferred": []},
            "resolutions": {},
            "options": {
                "remove_ranks_under": -10000000000,
                "allow_english_in_languages": False,
                "remove_unknown_languages": False,
            },
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(config, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        return f"{base_url.rstrip('/')}/{encoded}/manifest.json"
