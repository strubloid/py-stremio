"""Base addon abstractions and reusable HTTP behavior."""
from abc import ABC, abstractmethod
from collections.abc import Callable
import base64
import json
import re
from urllib.parse import urlparse

import httpx

from .models import StreamInfo


class BaseAddon(ABC):
    """Base class for all Stremio addons."""

    name: str = "BaseAddon"
    base_url: str = ""
    api_key: str | None = None

    @abstractmethod
    def get_url(self, api_key: str | None = None) -> str:
        """Get the configured addon URL."""
        pass

    @abstractmethod
    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        """Query addon for streams."""
        pass

    def query_stream_url(self, type_: str, id_: str) -> str:
        """Build the stream query URL."""
        base_url = self.get_url(self.api_key).rstrip("/")
        if base_url.endswith("/manifest.json"):
            base_url = base_url.removesuffix("/manifest.json")
        return f"{base_url}/stream/{type_}/{id_}.json"

    def fetch_streams(self, url: str) -> list[dict]:
        """Fetch raw streams from an addon URL."""
        try:
            response = httpx.get(
                url,
                timeout=8,
                headers={"User-Agent": "Stremio/4.4.168", "Accept": "application/json"},
            )
            response.raise_for_status()
            return response.json().get("streams", [])
        except Exception as exc:
            from ..error_logger import log_error

            log_error(f"fetch_streams({self.name})", exc, url)
            return []

    def parse_streams(self, streams_data: list[dict]) -> list[StreamInfo]:
        """Parse stream dictionaries into StreamInfo objects."""
        return [
            StreamInfo(
                name=stream.get("name", "unknown"),
                url=stream.get("url"),
                info_hash=_stream_info_hash(stream),
                file_idx=_stream_file_idx(stream),
                title=stream.get("title"),
                addon_name=self.name,
                filename=(stream.get("behaviorHints") or {}).get("filename"),
            )
            for stream in streams_data
        ]


def _stream_info_hash(stream: dict) -> str | None:
    """Extract a torrent info hash from common Stremio stream shapes."""
    info_hash = stream.get("infoHash")
    if info_hash:
        return str(info_hash)

    # Torrentio RD streams often only expose the hash inside behaviorHints
    # and the RD proxy URL. Keep it so failed RD proxy redirects can fall back
    # to the RealDebrid API instead of giving up.
    binge_group = (stream.get("behaviorHints") or {}).get("bingeGroup") or ""
    if binge_group.startswith("torrentio|"):
        candidate = binge_group.split("|", 1)[1].strip()
        if candidate:
            return candidate

    return _torrentio_resolve_parts(stream.get("url"))[0]


def _stream_file_idx(stream: dict) -> int | None:
    """Extract the file index from common Stremio stream shapes."""
    file_idx = stream.get("fileIdx")
    if file_idx is not None:
        try:
            return int(file_idx)
        except (TypeError, ValueError):
            return None

    return _torrentio_resolve_parts(stream.get("url"))[1]


def _torrentio_resolve_parts(url: str | None) -> tuple[str | None, int | None]:
    """Return (info_hash, file_idx) from Torrentio RD proxy resolve URLs."""
    if not url or "/resolve/" not in url:
        return None, None

    try:
        parts = [part for part in urlparse(url).path.split("/") if part]
        resolve_index = parts.index("resolve")
    except (ValueError, TypeError):
        return None, None

    # /resolve/{debrid}/{api_key}/{info_hash}/{season_or_null}/{file_idx}/...
    if len(parts) <= resolve_index + 4:
        return None, None

    info_hash = parts[resolve_index + 3] or None
    file_idx = None
    if len(parts) > resolve_index + 5:
        try:
            file_idx = int(parts[resolve_index + 5])
        except (TypeError, ValueError):
            file_idx = None

    return info_hash, file_idx


class HttpAddon(BaseAddon):
    """Reusable addon implementation for standard Stremio stream endpoints."""

    def get_streams(self, type_: str, id_: str) -> list[StreamInfo]:
        url = self.query_stream_url(type_, id_)
        streams_data = self.fetch_streams(url)
        return self.parse_streams(streams_data)


# ── RD injection registry for UrlAddon ──────────────────────────────────
# Maps a URL substring to an injector function(base_url, api_key) -> str.
# This lets addons loaded from addons.txt get the RD key injected at
# request time without baking the key into the file.
URL_RD_INJECTORS: dict[str, Callable[[str, str], str]] = {}


def build_comet_config_url(base_url: str, api_key: str) -> str:
    """Return a Comet URL configured for RealDebrid playback URLs.

    Plain Comet URLs return torrent-only streams.  Stremio's configured Comet
    URL embeds a base64 JSON config with the RD key, making Comet return
    `/playback/...` URLs that the app can download directly instead of relying
    on slower/less-reliable info_hash resolution.
    """
    parsed_base = urlparse(base_url)
    if parsed_base.netloc in {"comet.feels.legal", "comet.elfhosted.com"}:
        base_url = f"{parsed_base.scheme}://{parsed_base.netloc}"
    config = {
        "maxResultsPerResolution": 0,
        "maxSize": 0,
        "cachedOnly": False,
        "sortCachedUncachedTogether": False,
        "removeTrash": True,
        "resultFormat": ["all"],
        "debridServices": [{"service": "realdebrid", "apiKey": api_key}],
        "enableTorrent": False,
        "deduplicateStreams": False,
        "scrapeDebridAccountTorrents": False,
        "debridStreamProxyPassword": "",
        "languages": {"required": [], "allowed": [], "exclude": [], "preferred": []},
        "resolutions": {},
        "options": {
            "remove_ranks_under": -10000000000,
            "allow_english_in_languages": False,
            "remove_unknown_languages": False,
        },
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(config, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"{base_url.rstrip('/')}/{encoded}/manifest.json"


def build_hdhub_config_url(base_url: str) -> str:
    """Return an HDHub URL configured with quality preferences.

    HDHub URLs embed a small base64 JSON config for quality and sort
    preferences.  This function builds that config dynamically.
    """
    parsed_base = urlparse(base_url)
    config = {
        "torbox": "unset",
        "qualities": "2160p,1080p,720p",
        "sort": "desc",
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(config, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"{base_url.rstrip('/')}/{encoded}/manifest.json"


def build_torrentio_config_url(base_url: str, api_key: str) -> str:
    """Inject RealDebrid into clean Torrentio URLs used from server caches."""
    parsed = urlparse(base_url.rstrip("/"))
    path = parsed.path.strip("/")
    parts = [part for part in path.split("|") if part]
    parts = [part for part in parts if not part.startswith("realdebrid=")]
    if parts:
        config_path = "|".join([*parts, f"realdebrid={api_key}"])
    else:
        config_path = f"realdebrid={api_key}"
    return f"{parsed.scheme}://{parsed.netloc}/{config_path}/"


def build_guindex_config_url(base_url: str, api_key: str) -> str:
    """Inject RealDebrid into clean Guindex URLs used from server caches."""
    parsed = urlparse(base_url.rstrip("/"))
    clean_path = re.sub(r"/realdebrid/[^/]+", "", parsed.path).rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{clean_path}/realdebrid/{api_key}/"


def register_rd_injector(url_match: str, injector: Callable[[str, str], str]) -> None:
    """Register a URL pattern for automatic RD key injection in UrlAddon.

    Args:
        url_match: Substring to match in the addon URL
                   (e.g. 'intell-debridsearch.nepiraw.com').
        injector: Callable(base_url, api_key) returning the injected URL.
    """
    URL_RD_INJECTORS[url_match] = injector


class UrlAddon(HttpAddon):
    """Generic addon backed by a configured URL from addons.txt or other sources.

    The RD key is injected at request time via `get_url(api_key)` when the
    URL matches a registered injection pattern — no key is stored in the file.
    """

    def __init__(self, url: str):
        self._base_url = url.rstrip("/").replace("/manifest.json", "")
        self.name = self._name_from_url(self._base_url)

    def get_url(self, api_key: str | None = None) -> str:
        if not api_key:
            return self._base_url

        url = self._base_url.rstrip("/")

        # Try registered RD injection patterns
        for match_str, injector in URL_RD_INJECTORS.items():
            if match_str in url:
                return injector(url, api_key)

        return self._base_url

    @staticmethod
    def _name_from_url(url: str) -> str:
        parts = url.split("/")
        for part in reversed(parts):
            if part and not part.startswith("http") and not part.startswith("?"):
                return part[:30]
        return parts[-2][:30] if len(parts) > 1 else "UrlAddon"


# ── Register RD injection patterns for known addons ─────────────────────
# These addons are not in the built-in set but can use RD when the key
# is injected at request time.  Built-in addons (Torrentio, Guindex, etc.)
# have their own get_url() methods and are registered in factory.py.

register_rd_injector(
    "nyaa-scraper-stremio-addon.nmtl.app",
    lambda url, key: f"{url}/source=nyaa&rd={key}&v=1.9.1/",
)

# intell-debridsearch has its own built-in class (IntellDebridSearchAddon), but
# this injector is also needed for the server-URL path (create_addon_manager_from_urls)
# where working URLs are used as UrlAddon instances, not built-in addons.
register_rd_injector(
    "intell-debridsearch.nepiraw.com",
    lambda url, key: f"{url}/realdebrid={key}/",
)

register_rd_injector(
    "torrentio.strem.fun",
    build_torrentio_config_url,
)

register_rd_injector(
    "guindex-stremio.vercel.app",
    build_guindex_config_url,
)

register_rd_injector(
    "comet.feels.legal",
    build_comet_config_url,
)

register_rd_injector(
    "comet.elfhosted.com",
    build_comet_config_url,
)
