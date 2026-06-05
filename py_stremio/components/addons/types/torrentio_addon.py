"""Torrentio URL configuration."""

from urllib.parse import urlparse

from .addon_url_configurer import AddonUrlConfigurer


class TorrentioAddonConfigurer(AddonUrlConfigurer):
    """Inject RealDebrid into clean Torrentio URLs."""

    host_match = "torrentio.strem.fun"

    def normalize(self, url: str) -> str:
        parsed = urlparse(url.strip().rstrip("/").removesuffix("/manifest.json"))
        path = parsed.path.strip("/")
        parts = [part for part in path.split("|") if part and not part.startswith("realdebrid=")]
        return f"{parsed.scheme}://{parsed.netloc}" + (f"/{'|'.join(parts)}" if parts else "")

    def configure(self, base_url: str, api_key: str) -> str:
        parsed = urlparse(base_url.rstrip("/"))
        path = parsed.path.strip("/")
        parts = [part for part in path.split("|") if part]
        parts = [part for part in parts if not part.startswith("realdebrid=")]
        if parts:
            config_path = "|".join([*parts, f"realdebrid={api_key}"])
        else:
            config_path = f"realdebrid={api_key}"
        return f"{parsed.scheme}://{parsed.netloc}/{config_path}/"
