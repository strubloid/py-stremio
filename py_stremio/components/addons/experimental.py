"""Experimental addon registry — last-resort addon URLs.

Experimental addons are only queried when all normal addons (built-in + addons.txt)
fail to produce a working download for a given episode or movie.  This tier gives
the user a safety net for niche content, unstable addons, or geographic fallbacks
without polluting the primary search path.

File format (addons_experimental.txt):
  Same as addons.txt: one URL per line, '#' for comments.
  Each URL is a clean manifest URL, exactly like the main file.

Usage:
    from py_stremio.components.addons.experimental import (
        load_experimental_urls,
        ExperimentalAddonManager,
    )

    urls = load_experimental_urls()
    manager = ExperimentalAddonManager(urls)
    streams, working = manager.search(type_, stremio_id)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from py_stremio.components.addons.base import UrlAddon
from py_stremio.components.addons.manager import SEARCH_CONCURRENCY
from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.configs.app_settings import settings

EXPERIMENTAL_FILE = "addons_experimental.txt"


def _find_project_root() -> Path:
    """Walk up from cwd to find pyproject.toml (same logic as discovery.py)."""
    start = Path.cwd()
    for p in [start] + list(start.parents):
        if (p / "pyproject.toml").exists():
            return p
    return start


def load_experimental_urls() -> list[str]:
    """Load experimental addon URLs from addons_experimental.txt.

    Returns an empty list when the file does not exist or contains no
    uncommented lines.  URLs are returned in file order, stripped.
    """
    project_root = _find_project_root()
    path = project_root / EXPERIMENTAL_FILE

    if not path.exists():
        return []

    urls: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comments
        cleaned = line.split("#")[0].strip()
        if cleaned:
            urls.append(cleaned)
    return urls


class ExperimentalAddonManager:
    """Lightweight addon manager tailored for experimental URLs.

    Unlike the primary AddonManager, this one:
    - Only queries addon URLs from the experimental file
    - Always runs with best-effort semantics (no persistence)
    - Returns streams + working URLs, caller decides what to do
    """

    def __init__(self, urls: list[str] | None = None):
        self.addons: list[UrlAddon] = []
        self.api_key = settings.REAL_DEBRID_API_KEY

        if urls:
            for raw_url in urls:
                try:
                    addon = UrlAddon(raw_url)
                    addon.api_key = self.api_key
                    self.addons.append(addon)
                except Exception:
                    pass  # skip malformed URLs silently

    def search(
        self,
        type_: str,
        stremio_id: str,
    ) -> tuple[list[StreamInfo], list[str]]:
        """Search all experimental addons for *stremio_id*.

        Returns (streams, working_urls) where working_urls are the
        normalised URLs of addons that returned at least one stream.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from py_stremio.components.configs.app_settings import settings

        if not self.addons:
            return [], []

        total = len(self.addons)
        all_streams: list[StreamInfo] = []
        working_urls: list[str] = []
        result_lock = threading_lock()

        executor = ThreadPoolExecutor(max_workers=min(SEARCH_CONCURRENCY, total))
        futures = {}
        try:
            futures = {
                executor.submit(self._try_addon, addon, type_, stremio_id): addon
                for addon in self.addons
            }
            for future in as_completed(futures):
                addon = futures[future]
                try:
                    streams = future.result(timeout=20)
                except Exception:
                    streams = []
                if streams:
                    with result_lock:
                        addon_url = self._addon_url(addon)
                        for s in streams:
                            s.addon_url = s.addon_url or addon_url
                        all_streams.extend(streams)
                        if addon_url and addon_url not in working_urls:
                            working_urls.append(addon_url)
        finally:
            executor.shutdown(wait=True)

        return all_streams, working_urls

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _try_addon(addon: UrlAddon, type_: str, id_: str) -> list[StreamInfo]:
        """Query one experimental addon URL."""
        from py_stremio.components.addons.addon_search_service import query_addon_for_streams

        try:
            url = addon.get_url(getattr(addon, "api_key", None))
        except TypeError:
            url = addon.get_url()

        if not url:
            return []
        return query_addon_for_streams(url, type_, id_)

    @staticmethod
    def _addon_url(addon: UrlAddon) -> str:
        """Return the clean persistence-safe URL."""
        from py_stremio.components.stremio.stremio_url import normalize_manifest_url

        try:
            url = addon.get_url(None)
        except TypeError:
            url = addon.get_url()
        return normalize_manifest_url(url)


# Re-use the same threading.Lock from the standard library
def threading_lock() -> Any:
    from threading import Lock
    return Lock()
