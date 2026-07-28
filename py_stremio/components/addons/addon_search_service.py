"""Addon search and stream parsing helpers."""
import threading
import time
from typing import Any

from py_stremio.components.addons.base import BaseAddon
from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.addons.manager import SEARCH_CONCURRENCY
from py_stremio.components.stremio.stremio_url import normalize_manifest_url, unique_manifest_urls
from py_stremio.utils.cancellation import request_shutdown, shutdown_executor_now, shutdown_requested


# Result of one preflight probe. The three states matter:
#   ALIVE          — addon returned usable streams
#   INDETERMINATE  — addon's host was rate-limit saturated; we don't know
#                    whether the addon is genuinely empty for this content
#   DEAD           — addon returned no streams and was not rate-limited
PreflightStatus = str  # one of "alive", "indeterminate", "dead"


class PreflightResult:
    """Structured outcome of a preflight pass.

    Attributes:
        alive: Addons that returned at least one usable stream.
        indeterminate: Addons that could not be probed because their host
            was rate-limit saturated.  Their status is unknown — the next
            preflight pass may find them alive.
        dead: Addons that returned no usable streams AND were not
            rate-limited.  Safe to skip for the rest of the run.
    """

    __slots__ = ("alive", "indeterminate", "dead")

    def __init__(
        self,
        alive: list[str] | None = None,
        indeterminate: list[str] | None = None,
        dead: list[str] | None = None,
    ) -> None:
        self.alive: list[str] = list(alive or [])
        self.indeterminate: list[str] = list(indeterminate or [])
        self.dead: list[str] = list(dead or [])

    @property
    def has_working(self) -> bool:
        return bool(self.alive)

    @property
    def has_unknown(self) -> bool:
        return bool(self.indeterminate)

    def __bool__(self) -> bool:
        return self.has_working

    def to_url_set(self) -> set[str]:
        return set(self.alive) | set(self.indeterminate) | set(self.dead)


def _coerce_preflight(value: Any) -> "PreflightResult":
    """Accept either a :class:`PreflightResult` or a plain list of URLs.

    Plain lists are treated as a fully-alive result for backward
    compatibility with tests and call sites that still pass raw lists.
    Returning a uniform :class:`PreflightResult` keeps callers simple.
    """
    if isinstance(value, PreflightResult):
        return value
    if isinstance(value, (list, tuple, set)):
        return PreflightResult(alive=list(value))
    return PreflightResult()


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
            behavior_hints = stream.get("behaviorHints") or {}
            streams.append(
                StreamInfo(
                    name=stream.get("name", "unknown"),
                    url=stream.get("url"),
                    info_hash=stream.get("infoHash"),
                    file_idx=stream.get("fileIdx"),
                    title=stream.get("title"),
                    filename=behavior_hints.get("filename"),
                    addon_url=normalize_manifest_url(addon_url),
                    seeders=parsed_seeders,
                    imdb_id=(
                        stream.get("imdb_id")
                        or stream.get("imdbId")
                        or behavior_hints.get("imdb_id")
                        or behavior_hints.get("imdbId")
                    ),
                    subtitle_tracks=_parse_subtitle_tracks(stream),
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


def _parse_subtitle_tracks(stream: dict) -> list[dict] | None:
    """Extract the Stremio subtitle tracks array from a raw stream dict.

    Returns None when no subtitle metadata is present.
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
    preferred_languages: list[str] | None = None,
) -> tuple[list, list[str]]:
    """Search known working addons first, then remaining configured addons.

    When *preferred_languages* contains ``"english"`` (or the default
    PREFERRED_LANGUAGES is english), streams are filtered for English
    subtitle support after each search phase.  If no English-subtitled
    streams are found after exhausting all addons, a final pass returns
    *all* streams (unfiltered) as a last resort — this prevents blocking
    downloads entirely when no addon provides confirmed English subs.
    """
    from py_stremio.components.download.stream_download import filter_for_english_subtitles

    need_english = _should_enforce_english(preferred_languages)

    # ── Phase 1: search working (cached) addons ──
    working_streams, working_urls = search_working_addons_for_streams(
        type_,
        stremio_id,
        working_addons,
    )

    if need_english and working_streams:
        english_working = filter_for_english_subtitles(working_streams)
        if english_working:
            return english_working, working_urls

    # ── Phase 2: search remaining (all) addons ──
    remaining_streams, remaining_urls = search_remaining_addons_for_streams(
        type_,
        stremio_id,
        excluded_addons=working_addons,
    )
    all_urls = unique_manifest_urls([*working_urls, *remaining_urls])

    if need_english:
        combined_streams = [*working_streams, *remaining_streams]
        english_all = filter_for_english_subtitles(combined_streams)
        if english_all:
            return english_all, all_urls

        # ── Phase 3 (last resort): return all streams unfiltered ──
        if combined_streams:
            return combined_streams, all_urls
        return [], all_urls

    return (
        [*working_streams, *remaining_streams],
        all_urls,
    )


def _should_enforce_english(preferred_languages: list[str] | None) -> bool:
    """Return True when English subtitle enforcement should be active.

    Checks both the explicit *preferred_languages* argument and the
    global ``PREFERRED_LANGUAGES`` setting so the two-pass search
    activates even when callers do not pass the parameter.
    """
    from py_stremio.components.configs.app_settings import settings

    if preferred_languages is not None:
        normalized = [lang.strip().lower() for lang in preferred_languages if lang and lang.strip()]
        return "english" in normalized

    global_pref = settings.PREFERRED_LANGUAGES
    normalized = [lang.strip().lower() for lang in global_pref if lang and lang.strip()]
    return "english" in normalized


# ── Pre-flight addon discovery ────────────────────────────────────────────────

_STAGGER_DELAY = 0.3    # 300ms between addon submission batches
_STAGGER_GROUP = 3      # how many addons to submit before a delay


def _preflight_streams_are_usable(
    streams: list[StreamInfo],
    *,
    title: str | None = None,
    season: int | None = None,
    episode: int | None = None,
    imdb_id: str | None = None,
) -> bool:
    """Require a representative stream to survive target validation.

    A non-empty addon response is not enough: some addons return generic
    catalogue entries for every request. Target context is optional to retain
    the generic preflight behavior for callers that do not have it.

    Quality preferences are deliberately NOT applied here — the preflight
    only needs to confirm the addon returned a stream that matches the
    target show/episode. The full quality filter (preferred + fallbacks +
    ``allow_higher``/``allow_lower``) runs later in the download path.
    """
    if not streams:
        return False
    if not title:
        return True

    from py_stremio.components.download.stream_download import select_quality_streams

    return bool(select_quality_streams(
        streams,
        preferred_quality="1080p",
        preferred_languages=[],
        target_season=season,
        target_episode=episode,
        title=title,
        target_imdb_id=imdb_id,
        quality_fallbacks=["2160p", "720p", "480p", "360p"],
        allow_higher=True,
        allow_lower=True,
    ))


def preflight_discover_working_addons(
    type_: str,
    stremio_id: str,
    *,
    timeout_per_addon: int = 8,
    title: str | None = None,
    season: int | None = None,
    episode: int | None = None,
    imdb_id: str | None = None,
) -> PreflightResult:
    """Query ALL configured addons for one representative ID and classify
    them into alive / indeterminate / dead buckets.

    This is a one-time cost per season/movie — subsequent episode searches
    should only query addons that passed this preflight check, dramatically
    reducing per-episode latency.

    The result is a :class:`PreflightResult` with three lists:

    - ``alive`` — addons that returned at least one usable stream
    - ``indeterminate`` — addons whose host was rate-limit saturated when
      probed; the next preflight pass may find them alive
    - ``dead`` — addons that returned no usable streams and were not
      rate-limited; safe to skip for the rest of the run

    Backward-compat: callers that only need the alive list should call
    :meth:`PreflightResult.alive` or pass the result to
    ``list(preflight(...).alive)``.
    """
    import concurrent.futures

    import py_stremio.components.addons as addons

    manager = addons.create_addon_manager()
    if not manager.addons:
        return PreflightResult()

    total = len(manager.addons)

    alive: list[str] = []
    indeterminate: list[str] = []
    dead: list[str] = []
    result_lock = threading.Lock()

    from .cloudscraper_client import CloudscraperError
    from .rate_limiter import get_rate_limiter

    limiter = get_rate_limiter()

    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=SEARCH_CONCURRENCY
    )
    futures = {}
    try:

        def _try_one(addon: BaseAddon) -> tuple[str, PreflightStatus]:
            try:
                url = addon.get_url(None)
            except TypeError:
                url = addon.get_url()
            url = normalize_manifest_url(url)
            if not url:
                return url, "dead"
            try:
                streams = addon.get_streams(type_, stremio_id)
            except CloudscraperError as exc:
                # The HTTP client wraps a per-host rate-limit cap as a
                # CloudscraperError. Distinguish that from a real failure
                # so the caller does not silence-cap the whole season.
                if limiter.is_saturated(url) or "Rate limit" in str(exc):
                    return url, "indeterminate"
                return url, "dead"
            except Exception:
                return url, "dead"
            try:
                live = _preflight_streams_are_usable(
                    streams,
                    title=title,
                    season=season,
                    episode=episode,
                    imdb_id=imdb_id,
                )
            except Exception:
                live = False
            return url, ("alive" if live else "dead")

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
                url, status = future.result(timeout=timeout_per_addon + 5)
            except Exception:
                url, status = None, "dead"

            if not url:
                continue
            with result_lock:
                if status == "alive" and url not in alive:
                    alive.append(url)
                elif status == "indeterminate" and url not in indeterminate:
                    indeterminate.append(url)
                elif status == "dead" and url not in dead:
                    dead.append(url)
    except KeyboardInterrupt:
        request_shutdown()
        shutdown_executor_now(executor, futures.keys())
        raise
    else:
        executor.shutdown(wait=True)

    return PreflightResult(alive=alive, indeterminate=indeterminate, dead=dead)
