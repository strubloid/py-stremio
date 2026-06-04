"""Shared helpers for Stremio addon/server URLs."""


def normalize_manifest_url(url: str | None) -> str:
    """Normalize addon URLs so config values can be compared reliably."""
    if not url:
        return ""
    return url.strip().rstrip("/").removesuffix("/manifest.json")


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
