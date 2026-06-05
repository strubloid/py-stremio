"""StremThru URL configuration."""

import base64
import json
from urllib.parse import urlparse

from .addon_url_configurer import AddonUrlConfigurer


class StremThruAddonConfigurer(AddonUrlConfigurer):
    """Build StremThru torz config URLs with RealDebrid store configured."""

    host_match = "stremthru.13377001.xyz"
    enabled = False

    def configure(self, base_url: str, api_key: str) -> str:
        parsed = urlparse(base_url.rstrip("/"))
        base_path = parsed.path.rstrip("/")
        if not base_path or base_path == "/":
            base_path = "/stremio/torz"
        elif "/stremio/torz" not in base_path:
            base_path = f"{base_path}/stremio/torz".replace("//", "/")
        else:
            base_path = "/stremio/torz"
        config = {"indexers": None, "stores": [{"c": "rd", "t": api_key}]}
        encoded = base64.urlsafe_b64encode(
            json.dumps(config, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        return f"{parsed.scheme}://{parsed.netloc}{base_path}/{encoded}/"
