"""Shared helper for building Sootio addon URLs."""

from .SootioAddonConfigurer import SootioAddonConfigurer


def build_sootio_url(base_url: str, api_key: str | None) -> str:
    """Build a Sootio addon URL, injecting RealDebrid if api_key is provided."""
    if api_key:
        return SootioAddonConfigurer().configure(base_url, api_key)
    return base_url
