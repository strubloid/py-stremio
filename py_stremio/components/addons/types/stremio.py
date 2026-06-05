"""Generic Stremio manifest URL handling."""

from .addon_url_configurer import AddonUrlConfigurer


class StremioAddonConfigurer(AddonUrlConfigurer):
    """Normalize final-product Stremio manifest URLs into queryable addon bases."""

    host_match = "/manifest.json"

    def matches(self, url: str) -> bool:
        return url.rstrip("/").endswith("/manifest.json")

    def configure(self, base_url: str, api_key: str) -> str:
        return base_url.rstrip("/").removesuffix("/manifest.json")
