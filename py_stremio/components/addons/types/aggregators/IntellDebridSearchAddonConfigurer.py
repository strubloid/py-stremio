"""Intell Debrid Search URL configuration."""

from ..addon_url_configurer import AddonUrlConfigurer


class IntellDebridSearchAddonConfigurer(AddonUrlConfigurer):
    """Inject RealDebrid into Intell Debrid Search resolver URLs."""

    host_match = "intell-debridsearch.nepiraw.com"

    def configure(self, base_url: str, api_key: str) -> str:
        return f"{base_url.rstrip('/')}/realdebrid={api_key}/"
