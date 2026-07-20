"""Addon URL configuration registry.

Clean addon URLs are stored in addons.txt and per-folder server caches.  This
module chooses the host-specific rule that turns a clean URL into the runtime
URL required by that addon, usually by injecting the RealDebrid key from .env.
"""

from collections.abc import Callable

from .types import (
    AddonUrlConfigurer,
    BrazucaAddonConfigurer,
    CometAddonConfigurer,
    GuindexAddonConfigurer,
    HDHubAddonConfigurer,
    IntellDebridSearchAddonConfigurer,
    MeteorAddonConfigurer,
    NyaaAddonConfigurer,
    SootioAddonConfigurer,
    StremioAddonConfigurer,
    StremThruAddonConfigurer,
    TorrentioAddonConfigurer,
    YomiAddonConfigurer,
)

_ADDON_CONFIGURERS: list[AddonUrlConfigurer] = [
    StremioAddonConfigurer(),
    NyaaAddonConfigurer(),
    IntellDebridSearchAddonConfigurer(),
    TorrentioAddonConfigurer(),
    GuindexAddonConfigurer(),
    CometAddonConfigurer(),
    HDHubAddonConfigurer(),
    BrazucaAddonConfigurer(),
    StremThruAddonConfigurer(),
    MeteorAddonConfigurer(),
    SootioAddonConfigurer(),
    YomiAddonConfigurer(),
]

# Backward-compatible custom injector registry used by tests and any local
# extensions.  Prefer adding a class in addons/types for permanent rules.
URL_RD_INJECTORS: dict[str, Callable[[str, str], str]] = {}


def is_addon_url_enabled(base_url: str) -> bool:
    """Return False when a clean URL matches a disabled addon type rule."""
    url = base_url.rstrip("/")
    for configurer in _ADDON_CONFIGURERS:
        if configurer.matches(url):
            return configurer.enabled
    return True


def configure_addon_url(base_url: str, api_key: str | None) -> str:
    """Return the runtime URL for *base_url* using a host-specific rule."""
    if not api_key:
        return base_url

    url = base_url.rstrip("/")
    for configurer in _ADDON_CONFIGURERS:
        if not configurer.enabled:
            continue
        if configurer.matches(url):
            return configurer.configure(url, api_key)

    for match_str, injector in URL_RD_INJECTORS.items():
        if match_str in url:
            return injector(url, api_key)

    return base_url


def normalize_addon_url(url: str | None) -> str:
    """Return the clean persisted URL using the matching addon type rule."""
    if not url:
        return ""

    stripped_url = url.strip().rstrip("/").removesuffix("/manifest.json")
    for configurer in _ADDON_CONFIGURERS:
        if configurer.matches(stripped_url):
            return configurer.normalize(stripped_url)
    return stripped_url


def register_rd_injector(url_match: str, injector: Callable[[str, str], str]) -> None:
    """Register a custom URL injector for local/non-core addon rules."""
    URL_RD_INJECTORS[url_match] = injector
