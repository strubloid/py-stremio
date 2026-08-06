"""Intell Debrid Search URL configuration — DISABLED.

This addon requires Stremio's signed config protocol (POST /encrypt-config
with provider + API key, receiving an encrypted manifest URL back).  The
simple ``realdebrid=key`` suffix that other addons accept is not supported
here — every stream query returns zero results with that approach.

The configurer is kept as a disabled placeholder so the URL
``intell-debridsearch.nepiraw.com`` is not loaded as a generic UrlAddon
from addon files and searched repeatedly for no benefit.
"""

from ..addon_url_configurer import AddonUrlConfigurer


class IntellDebridSearchAddonConfigurer(AddonUrlConfigurer):
    """Intelligent Debrid Search — requires Stremio signed config, not URL-based."""

    host_match = "intell-debridsearch.nepiraw.com"
    enabled = False

    def configure(self, base_url: str, api_key: str) -> str:
        return f"{base_url.rstrip('/')}/realdebrid={api_key}/"
