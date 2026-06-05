"""Shared helpers for Stremio addon/server URLs."""

from py_stremio.components.addons.addon import normalize_addon_url


def normalize_manifest_url(url: str | None) -> str:
    """Normalize addon URLs so config values can be compared reliably.

    Persisted server URLs must not contain RealDebrid keys. Runtime addon
    types own host-specific normalization rules; this function is a Stremio
    compatibility wrapper for callers that normalize server/addon URLs.
    """
    return normalize_addon_url(url)


def unique_manifest_urls(urls: list[str] | None) -> list[str]:
    """Return normalized addon URLs in input order without duplicates."""
    unique_urls = []
    seen = set()
    for url in urls or []:
        normalized = normalize_manifest_url(url)
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_urls.append(normalized)
    return unique_urls
