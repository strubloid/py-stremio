"""Yomi URL configuration."""

import base64
import json
from urllib.parse import quote, urlparse

from ..addon_url_configurer import AddonUrlConfigurer


class YomiAddonConfigurer(AddonUrlConfigurer):
    """Build Yomi's nested URL-encoded/base64 RealDebrid config."""

    host_match = "yomi.ruka.pw"

    def normalize(self, url: str) -> str:
        parsed = urlparse(url.strip().rstrip("/").removesuffix("/manifest.json"))
        return f"{parsed.scheme}://{parsed.netloc}"

    def configure(self, base_url: str, api_key: str) -> str:
        parsed_base = urlparse(base_url)
        clean_base_url = f"{parsed_base.scheme}://{parsed_base.netloc}"
        config = {
            "useEnglishTitles": False,
            "showLatest": True,
            "showTrending": True,
            "showTop": True,
            "hideUncached": False,
            "resolutions": ["8K", "4K", "2K", "1080p", "720p", "480p", "SD"],
            "rdKey": api_key,
            "language": ["ENG"],
        }
        inner = base64.urlsafe_b64encode(
            json.dumps(config, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        outer = quote(json.dumps({"Yomi": inner}, separators=(",", ":")), safe="")
        return f"{clean_base_url}/{outer}/"
