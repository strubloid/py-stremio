"""Addon search and stream parsing helpers."""
from typing import Any

import httpx

from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.stremio.stremio_url import normalize_manifest_url, unique_manifest_urls


def query_addon_for_streams(addon_url: str, type_: str, id_: str) -> list[StreamInfo]:
    """Query a Stremio addon for streams."""
    streams = []
    url = f"{addon_url.rstrip('/')}/stream/{type_}/{id_}.json"

    print(f"    Querying: {url}")

    try:
        response = httpx.get(
            url,
            timeout=10,
            headers={"User-Agent": "Stremio/4.4.168", "Accept": "application/json"},
        )
        response.raise_for_status()
        data = response.json()

        for stream in data.get("streams", []):
            streams.append(
                StreamInfo(
                    name=stream.get("name", "unknown"),
                    url=stream.get("url"),
                    info_hash=stream.get("infoHash"),
                    file_idx=stream.get("fileIdx"),
                    title=stream.get("title"),
                    filename=(stream.get("behaviorHints") or {}).get("filename"),
                    addon_url=normalize_manifest_url(addon_url),
                )
            )
    except httpx.RequestError as e:
        print(f"    Network error: {e}")
        from py_stremio.components.errors.error_logger import log_error

        log_error("query_addon", e, url)
    except Exception as e:
        print(f"    Error: {e}")
        from py_stremio.components.errors.error_logger import log_error

        log_error("query_addon", e, url)

    return streams


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

    print(f"    First trying {len(working_urls)} known working addons...")
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
        print(f"    Searching {len(manager.addons)} remaining addons...")
    else:
        print(f"    Searching all {len(manager.addons)} addons...")

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
