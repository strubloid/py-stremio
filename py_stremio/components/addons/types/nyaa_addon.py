"""Nyaa scraper URL configuration."""

from .addon_url_configurer import AddonUrlConfigurer


class NyaaAddonConfigurer(AddonUrlConfigurer):
    """Inject source/version/RD settings for nyaa-scraper-stremio."""

    host_match = "nyaa-scraper-stremio-addon.nmtl.app"

    def configure(self, base_url: str, api_key: str) -> str:
        return f"{base_url.rstrip('/')}/source=nyaa&rd={api_key}&v=1.9.1/"
