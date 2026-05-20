"""Multi-addon support for finding streams."""
import httpx
from dataclasses import dataclass
from typing import Any

from .settings import settings


ADDONS = [
    "https://torrentio.strem.fun/realdebrid={api_key}/",
    "https://torrentio.strem.fun/sort=seeders|realdebrid={api_key}/",
    "https://anime-kitsu.strem.fun/manifest.json",
    "https://thepiratebay-plus.strem.fun/manifest.json",
    "https://mediafusion.elfhosted.com/manifest.json",
]


def load_addons_from_file(filepath: str | None = None) -> list[str]:
    """Load addon URLs from file or return defaults."""
    if filepath:
        try:
            with open(filepath, "r") as f:
                return [line.strip() for line in f if line.strip() and not line.startswith("#")]
        except FileNotFoundError:
            pass
    return []


def get_addon_urls() -> list[str]:
    """Get list of addon URLs to try."""
    custom_addons = load_addons_from_file("addons.txt")
    if custom_addons:
        return custom_addons

    addons = []
    api_key = settings.REAL_DEBRID_API_KEY or ""

    for template in ADDONS:
        if "{api_key}" in template:
            if api_key:
                url = template.replace("{api_key}", api_key)
                addons.append(url)
        else:
            addons.append(template)

    return addons


@dataclass
class StreamInfo:
    name: str
    url: str | None = None
    info_hash: str | None = None
    file_idx: int | None = None
    title: str | None = None
    addon_url: str = ""


def query_addon_streams(
    addon_url: str,
    type_: str,
    id_: str
) -> list[StreamInfo]:
    """Query a single addon for streams."""
    streams = []
    url = f"{addon_url.rstrip('/')}/stream/{type_}/{id_}.json"

    try:
        response = httpx.get(
            url,
            timeout=15,
            headers={"User-Agent": "Stremio/4.4.168", "Accept": "application/json"}
        )
        response.raise_for_status()
        data = response.json()

        for stream in data.get("streams", []):
            streams.append(StreamInfo(
                name=stream.get("name", "unknown"),
                url=stream.get("url"),
                info_hash=stream.get("infoHash"),
                file_idx=stream.get("fileIdx"),
                title=stream.get("title"),
                addon_url=addon_url
            ))
    except Exception:
        pass

    return streams


def search_all_addons(
    type_: str,
    id_: str,
    max_addons: int = 3
) -> list[StreamInfo]:
    """Search multiple addons and return all streams found."""
    all_streams = []
    addon_urls = get_addon_urls()

    for addon_url in addon_urls[:max_addons]:
        streams = query_addon_streams(addon_url, type_, id_)
        if streams:
            print(f"    Found {len(streams)} streams from {addon_url.split('/')[2]}")
            all_streams.extend(streams)
            break

    return all_streams