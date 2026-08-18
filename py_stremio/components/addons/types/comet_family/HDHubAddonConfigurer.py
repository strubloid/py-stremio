"""HDHub URL configuration."""

import base64
import json
import re
from urllib.parse import urlparse

from ..addon_url_configurer import AddonUrlConfigurer


# TorBox API keys are UUID-formatted (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx).
# RealDebrid keys are mixed alphanumeric without dashes. Detecting by shape
# lets the same configurer safely accept a key passed via either:
#   - HDHubAddon.get_url (which reads HDHUB_DEBRID_KEY — the intended path)
#   - configure_addon_url (which routes RealDebrid from the auto-injection flow)
# Without this guard, the auto-injected RealDebrid key would be dropped into
# HDHub's ``torbox`` field, which HDHub does not accept.
_TORBOX_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


class HDHubAddonConfigurer(AddonUrlConfigurer):
    """Build HDHub quality/sort preference config URLs."""

    host_match = "hdhub.thevolecitor.qzz.io"

    def normalize(self, url: str) -> str:
        parsed = urlparse(url.strip().rstrip("/").removesuffix("/manifest.json"))
        return f"{parsed.scheme}://{parsed.netloc}"

    def configure(self, base_url: str, api_key: str) -> str:
        # Accept only UUID-formatted TorBox keys. Any other shape
        # (RealDebrid alnum, empty string, or a stray placeholder from
        # the auto-RD injection path) is treated as "unset" so HDHub
        # falls back to its HLS placeholders instead of rejecting the
        # request outright.
        torbox = api_key if api_key and _TORBOX_UUID_RE.match(api_key) else "unset"
        config = {
            "torbox": torbox,
            "qualities": "2160p,1080p,720p",
            "sort": "desc",
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(config, separators=(",", ":")).encode()
        ).decode().rstrip("=")
        return f"{base_url.rstrip('/')}/{encoded}/manifest.json"
