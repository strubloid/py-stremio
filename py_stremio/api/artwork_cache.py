"""Download and cache IMDb/Cinemeta artwork on the local application disk."""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from py_stremio.storage.db import get_db_path


_CACHE_LOCK = threading.Lock()
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/avif": ".avif",
}
_APPROVED_IMAGE_HOSTS = {
    "images.metahub.space",
    "live.metahub.space",
    "episodes.metahub.space",
    "image.tmdb.org",
}


@dataclass(frozen=True)
class CachedArtwork:
    path: Path
    media_type: str


def _allowed_host(host: str | None) -> bool:
    return bool(host and (host in _APPROVED_IMAGE_HOSTS or host == "media-amazon.com" or host.endswith(".media-amazon.com")))


def get_cached_artwork(url: str) -> CachedArtwork:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or not _allowed_host(parsed.hostname):
        raise ValueError("Artwork URL is not from an approved HTTPS image host")

    cache_dir = get_db_path().parent / "artwork"
    cache_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(cache_dir, 0o700)
    except OSError:
        pass
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()

    with _CACHE_LOCK:
        for media_type, extension in _IMAGE_TYPES.items():
            cached = cache_dir / f"{key}{extension}"
            if cached.is_file():
                return CachedArtwork(cached, media_type)

        response = httpx.get(url, timeout=15, follow_redirects=True, headers={"User-Agent": "py-stremio/1.0"})
        response.raise_for_status()
        if not _allowed_host(response.url.host):
            raise ValueError("Artwork redirected to an unapproved image host")
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        extension = _IMAGE_TYPES.get(media_type)
        if extension is None or len(response.content) > _MAX_IMAGE_BYTES:
            raise ValueError("Artwork response is not a supported image or exceeds the size limit")

        target = cache_dir / f"{key}{extension}"
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=cache_dir, prefix=".art-", delete=False) as temp_file:
                temp_file.write(response.content)
                temp_path = Path(temp_file.name)
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, target)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)
        return CachedArtwork(target, media_type)
