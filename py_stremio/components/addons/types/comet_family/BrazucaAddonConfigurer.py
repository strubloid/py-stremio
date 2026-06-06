"""Brazuca Torrents URL configuration."""

from urllib.parse import urlparse

from ..addon_url_configurer import AddonUrlConfigurer


class BrazucaAddonConfigurer(AddonUrlConfigurer):
    """Inject RealDebrid into clean Brazuca Torrents URLs."""

    host_match = "brazuca-torrents.baby-beamup.club"

    def normalize(self, url: str) -> str:
        parsed = urlparse(url.strip().rstrip("/").removesuffix("/manifest.json"))
        return f"{parsed.scheme}://{parsed.netloc}"

    def configure(self, base_url: str, api_key: str) -> str:
        parsed = urlparse(base_url.rstrip("/"))
        clean_base_url = f"{parsed.scheme}://{parsed.netloc}"
        return f"{clean_base_url}/sort=size|realdebrid={api_key}/"
