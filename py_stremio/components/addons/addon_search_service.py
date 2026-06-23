"""Addon search and stream parsing helpers."""
import threading
import time
from typing import Any

from py_stremio.components.addons.base import BaseAddon
from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.addons.manager import SEARCH_CONCURRENCY
from py_stremio.components.stremio.stremio_url import normalize_manifest_url, unique_manifest_urls
from py_stremio.utils.cancellation import request_shutdown, shutdown_executor_now, shutdown_requested


def query_addon_for_streams(addon_url: str, type_: str, id_: str) -> list[StreamInfo]:
    """Query a Stremio addon for streams via cloudscraper."""
    streams = []
    url = f"{addon_url.rstrip('/')}/stream/{type_}/{id_}.json"
    addon_name = _name_from_url(addon_url)

    try:
        from .cloudscraper_client import addon_get

        data = addon_get(url, timeout=10)
        for stream in data.get("streams", []):
            seeders_raw = stream.get("seeders") or stream.get("peers")
            try:
                parsed_seeders = int(seeders_raw) if seeders_raw is not None else None
            except (ValueError, TypeError):
                parsed_seeders = None
            streams.append(
                StreamInfo(
                    name=stream.get("name", "unknown"),
                    url=stream.get("url"),
                    info_hash=stream.get("infoHash"),
                    file_idx=stream.get("fileIdx"),
                    title=stream.get("title"),
                    filename=(stream.get("behaviorHints") or {}).get("filename"),
                    addon_url=normalize_manifest_url(addon_url),
                    seeders=parsed_seeders,
                    imdb_id=stream.get("imdb_id"),
                )
            )
    except Exception as exc:
        from py_stremio.components.errors import report_error

        report_error(context=f"query_addon({addon_name})", exception=exc, url=url)

    return streams


def _name_from_url(url: str) -> str:
    """Extract a readable addon name from a URL's domain first segment.

    Examples:
      'https://torrentio.strem.fun/...'    → 'torrentio'
      'https://comet.elfhosted.com/...'    → 'comet'
      'https://podnapisi.net/...'          → 'podnapisi'
      'https://thepiratebay-plus.strem.fun/...' → 'thepiratebay-plus'
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.netloc or parsed.hostname or ""
    # Strip port
    if ":" in host:
        host = host.split(":")[0]
    # Return the first segment of the domain
    return host.split(".")[0][:30] if host else "unknown"


def configured_addon_url(addon: Any) -> str:
    """Return a normalized URL for an addon object."""
    try:
        url = addon.get_url(getattr(addon, "api_key", None))
    except TypeError:
        url = addon.get_url()
    return normalize_manifest_url(url)


def search_working_addons_for_streams(
    type_: str,
    stremio_id: str,
    working_addons: list[str] | None = None,
) -> tuple[list, list[str]]:
    """Search the per-folder verified server cache only."""
    import py_stremio.components.addons as addons

    working_urls = unique_manifest_urls(working_addons)
    if not working_urls:
        return [], []

    working_manager = addons.create_addon_manager_from_urls(working_urls)
    return working_manager.search_all_addons_and_collect_working(type_, stremio_id)


def search_remaining_addons_for_streams(
    type_: str,
    stremio_id: str,
    excluded_addons: list[str] | None = None,
) -> tuple[list, list[str]]:
    """Search all configured addons except the already-tried URLs."""
    import py_stremio.components.addons as addons

    excluded_urls = set(unique_manifest_urls(excluded_addons))
    searched_urls = set(excluded_urls)
    manager = addons.create_addon_manager()

    if excluded_urls:
        remaining_addons = []
        for addon in manager.addons:
            addon_url = configured_addon_url(addon)
            if not addon_url or addon_url in searched_urls:
                continue
            searched_urls.add(addon_url)
            remaining_addons.append(addon)
        manager.addons = remaining_addons

    if not manager.addons:
        return [], []
    return manager.search_all_addons_and_collect_working(type_, stremio_id)


def search_all_addons_for_streams(
    type_: str,
    stremio_id: str,
    working_addons: list[str] | None = None,
    max_addons: int = 3,
) -> tuple[list, list[str]]:
    """Search known working addons first, then remaining configured addons."""
    working_streams, working_urls = search_working_addons_for_streams(
        type_,
        stremio_id,
        working_addons,
    )
    remaining_streams, remaining_urls = search_remaining_addons_for_streams(
        type_,
        stremio_id,
        excluded_addons=working_addons,
    )
    return (
        [*working_streams, *remaining_streams],
        unique_manifest_urls([*working_urls, *remaining_urls]),
    )


# ── Pre-flight addon discovery ────────────────────────────────────────────────

_STAGGER_DELAY = 0.3    # 300ms between addon submission batches
_STAGGER_GROUP = 3      # how many addons to submit before a delay

def preflight_discover_working_addons(
    type_: str,
    stremio_id: str,
    *,
    timeout_per_addon: int = 8,
) -> list[str]:
    """Query ALL configured addons for one representative ID and return
    only the URLs of addons that returned usable streams.

    This is a one-time cost per season/movie — subsequent episode searches
    should only query addons that passed this preflight check, dramatically
    reducing per-episode latency.

    Returns a list of normalized addon URLs that returned at least one stream.
    """
    import concurrent.futures

    import py_stremio.components.addons as addons

    manager = addons.create_addon_manager()
    if not manager.addons:
        return []

    total = len(manager.addons)

    alive: list[str] = []
    result_lock = threading.Lock()

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=SEARCH_CONCURRENCY
    )
    futures = {}
    try:

        def _try_one(addon: BaseAddon) -> tuple[str, bool]:
            try:
                streams = addon.get_streams(type_, stremio_id)
                live = bool(streams)
            except Exception:
                live = False
            try:
                url = addon.get_url(None)
            except TypeError:
                url = addon.get_url()
            return normalize_manifest_url(url), live

        futures = {}
        # Stagger addon submission by 150ms to avoid an initial burst
        for i, addon in enumerate(manager.addons):
            if i > 0 and i % _STAGGER_GROUP == 0:
                time.sleep(_STAGGER_DELAY)
            futures[executor.submit(_try_one, addon)] = addon

        for future in concurrent.futures.as_completed(futures):
            if shutdown_requested():
                break
            addon = futures[future]
            try:
                url, live = future.result(timeout=timeout_per_addon + 5)
            except Exception:
                url, live = None, False

            if url and live:
                with result_lock:
                    if url not in alive:
                        alive.append(url)
    except KeyboardInterrupt:
        request_shutdown()
        shutdown_executor_now(executor, futures.keys())
        raise
    else:
        executor.shutdown(wait=True)

    return alive
