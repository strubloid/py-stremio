"""Base addon abstractions and reusable HTTP behavior."""
from abc import ABC, abstractmethod
from urllib.parse import urlparse

from .models import StreamInfo
from .cloudscraper_client import addon_get_streams


class BaseAddon(ABC):
    """Base class for all Stremio addons."""

    name: str = "BaseAddon"
    base_url: str = ""
    api_key: str | None = None
    enabled: bool = True

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
        """Fetch raw streams from an addon URL via cloudscraper."""
        return addon_get_streams(url, timeout=8, addon_name=self.name)

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
                addon_url=self.get_url(None),
                sources=stream.get("sources"),
                seeders=_stream_seeders(stream),
                imdb_id=_stream_imdb_id(stream),
                subtitle_tracks=_parse_subtitle_tracks(stream),
            )
            for stream in streams_data
            if _is_downloadable_stream_candidate(stream)
        ]


def _is_downloadable_stream_candidate(stream: dict) -> bool:
    """Return True only for streams the downloader can automate.

    Stremio addons sometimes return advisory rows as streams, e.g. a Reddit
    link explaining that non-debrid search is disabled. Those are useful in the
    Stremio UI but should not be treated as video downloads.
    """
    if not isinstance(stream, dict):
        return False

    if stream.get("externalUrl") and not stream.get("url") and not stream.get("infoHash"):
        return False

    info_hash = _stream_info_hash(stream)
    if info_hash:
        return True

    url = stream.get("url")
    if not url:
        return False

    name = str(stream.get("name") or "").lower()
    title = str(stream.get("title") or "").lower()
    description = str(stream.get("description") or "").lower()
    advisory_text = " ".join([name, title, description])
    advisory_markers = (
        "⛔",
        "⚠",
        "ℹ",
        "error",
        "disabled",
        "configure this addon",
        "access streams",
        "use a debrid provider",
        "not available",
    )
    if any(marker in advisory_text for marker in advisory_markers):
        return False

    parsed = urlparse(str(url))
    host = (parsed.netloc or "").lower()
    if host in {"www.reddit.com", "reddit.com", "old.reddit.com"}:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    return True


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


def _stream_seeders(stream: dict) -> int | None:
    seeders_raw = stream.get("seeders") or stream.get("peers")
    if seeders_raw is None:
        return None
    try:
        return int(seeders_raw)
    except (TypeError, ValueError):
        return None


def _stream_imdb_id(stream: dict) -> str | None:
    behavior_hints = stream.get("behaviorHints") or {}
    imdb_id = (
        stream.get("imdb_id")
        or stream.get("imdbId")
        or behavior_hints.get("imdb_id")
        or behavior_hints.get("imdbId")
    )
    return str(imdb_id) if imdb_id else None


def _parse_subtitle_tracks(stream: dict) -> list[dict] | None:
    """Extract the Stremio subtitle tracks array from a raw stream dict.

    Returns None when no subtitle metadata is present so callers can
    distinguish "addons returned no subtitles" from "addons returned an
    empty list".
    """
    raw = stream.get("subtitles")
    if not raw or not isinstance(raw, list):
        return None
    tracks: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        track: dict = {}
        if "url" in entry:
            track["url"] = entry["url"]
        if "label" in entry:
            track["label"] = entry["label"]
        if "flag" in entry:
            track["flag"] = entry["flag"]
        if track:
            tracks.append(track)
    return tracks or None


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


# ── Runtime URL configuration compatibility helpers ────────────────────────
# Permanent host-specific rules live in addons/addon.py + addons/types/.  These
# wrappers keep the old public imports working while moving the actual per-host
# behavior out of this base abstraction.
from .addon import URL_RD_INJECTORS, configure_addon_url, is_addon_url_enabled, register_rd_injector
from .types.comet_family.CometAddonConfigurer import CometAddonConfigurer
from .types.comet_family.GuindexAddonConfigurer import GuindexAddonConfigurer
from .types.comet_family.HDHubAddonConfigurer import HDHubAddonConfigurer
from .types.comet_family.StremThruAddonConfigurer import StremThruAddonConfigurer
from .types.torrentio_family.TorrentioAddonConfigurer import TorrentioAddonConfigurer


def build_comet_config_url(base_url: str, api_key: str) -> str:
    """Return a Comet URL configured for RealDebrid playback URLs."""
    return CometAddonConfigurer().configure(base_url, api_key)


def build_hdhub_config_url(base_url: str) -> str:
    """Return an HDHub URL configured with quality preferences."""
    return HDHubAddonConfigurer().configure(base_url, "")


def build_stremthru_config_url(base_url: str, api_key: str) -> str:
    """Return a StremThru URL configured with a RealDebrid store."""
    return StremThruAddonConfigurer().configure(base_url, api_key)


def build_torrentio_config_url(base_url: str, api_key: str) -> str:
    """Inject RealDebrid into clean Torrentio URLs used from server caches."""
    return TorrentioAddonConfigurer().configure(base_url, api_key)


def build_guindex_config_url(base_url: str, api_key: str) -> str:
    """Inject RealDebrid into clean Guindex URLs used from server caches."""
    return GuindexAddonConfigurer().configure(base_url, api_key)


class UrlAddon(HttpAddon):
    """Generic addon backed by a configured URL from addons.txt or other sources.

    The RD key is injected at request time via `get_url(api_key)` when the
    URL matches a registered injection pattern — no key is stored in the file.
    """

    def __init__(self, url: str):
        self._base_url = url.rstrip("/").replace("/manifest.json", "")
        self.name = self._name_from_url(self._base_url)
        self.enabled = is_addon_url_enabled(self._base_url)

    def get_url(self, api_key: str | None = None) -> str:
        return configure_addon_url(self._base_url, api_key)

    @staticmethod
    def _name_from_url(url: str) -> str:
        """Extract a readable addon name from a URL's domain first segment."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.netloc or parsed.hostname or ""
        if ":" in host:
            host = host.split(":")[0]
        return host.split(".")[0][:30] if host else "UrlAddon"
