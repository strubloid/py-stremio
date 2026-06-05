"""Shared helpers for Stremio addon/server URLs."""
import re
from urllib.parse import urlparse


def normalize_manifest_url(url: str | None) -> str:
    """Normalize addon URLs so config values can be compared reliably.

    Persisted server URLs must not contain RealDebrid keys.  Runtime addon
    classes/UrlAddon inject credentials from .env when needed.
    """
    if not url:
        return ""
    normalized = url.strip().rstrip("/").removesuffix("/manifest.json")
    parsed = urlparse(normalized)
    if parsed.netloc in {"comet.feels.legal", "comet.elfhosted.com"}:
        return f"{parsed.scheme}://{parsed.netloc}"
    if parsed.netloc == "torrentio.strem.fun":
        path = parsed.path.strip("/")
        parts = [part for part in path.split("|") if part and not part.startswith("realdebrid=")]
        return f"{parsed.scheme}://{parsed.netloc}" + (f"/{'|'.join(parts)}" if parts else "")
    if parsed.netloc == "guindex-stremio.vercel.app":
        clean_path = re.sub(r"/realdebrid/[^/]+", "", parsed.path).rstrip("/")
        return f"{parsed.scheme}://{parsed.netloc}{clean_path}"
    return normalized


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
