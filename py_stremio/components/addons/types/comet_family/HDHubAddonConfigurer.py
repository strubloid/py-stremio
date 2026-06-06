"""HDHub URL configuration."""

import base64
import json
from urllib.parse import urlparse

from ..addon_url_configurer import AddonUrlConfigurer


class HDHubAddonConfigurer(AddonUrlConfigurer):
    """Build HDHub quality/sort preference config URLs."""

    host_match = "hdhub.thevolecitor.qzz.io"

    def normalize(self, url: str) -> str:
        parsed = urlparse(url.strip().rstrip("/").removesuffix("/manifest.json"))
        return f"{parsed.scheme}://{parsed.netloc}"

    def configure(self, base_url: str, api_key: str) -> str:
        config = {
            "torbox": "unset",
            "qualities": "2160p,1080p,720p",
            "sort": "desc",
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(config, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        return f"{base_url.rstrip('/')}/{encoded}/manifest.json"
