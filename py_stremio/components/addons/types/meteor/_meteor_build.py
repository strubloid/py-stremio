"""Shared helper for building Meteor for the Weebs addon URLs."""

from .MeteorAddonConfigurer import MeteorAddonConfigurer


def build_meteor_url(base_url: str, api_key: str | None) -> str:
    """Build a Meteor addon URL, injecting RealDebrid if api_key is provided."""
    if api_key:
        return MeteorAddonConfigurer().configure(base_url, api_key)
    return base_url
