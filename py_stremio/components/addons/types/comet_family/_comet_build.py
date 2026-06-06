"""Shared helper for building Comet family addon URLs."""

from .CometAddonConfigurer import CometAddonConfigurer


def build_comet_url(base_url: str, api_key: str | None) -> str:
    """Build a Comet addon URL, injecting RealDebrid if api_key is provided."""
    if api_key:
        return CometAddonConfigurer().configure(base_url, api_key)
    return base_url
