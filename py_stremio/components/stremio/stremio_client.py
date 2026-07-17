"""Public Stremio client facade for stream search and downloads."""
from __future__ import annotations

from typing import Any, Callable

from py_stremio.components.addons.models import StreamInfo
from py_stremio.components.debrid.real_debrid_client import resolve_torrent_with_debrid
from py_stremio.components.configs.app_settings import settings
from py_stremio.components.addons.addon_search_service import (
    search_all_addons_for_streams,
    search_remaining_addons_for_streams,
    search_working_addons_for_streams,
)
from py_stremio.components.addons.experimental import (
    ExperimentalAddonManager,
    load_experimental_urls,
)
from py_stremio.components.stremio.stremio_ids import build_stremio_id
from py_stremio.components.stremio.stremio_metadata import get_imdb_id, get_series_imdb_id
from py_stremio.components.download.stream_download import (
    InvalidVideoDownloadError,
    StreamStallError,
    build_media_filename,
    can_retry_with_debrid,
    download_stream_to_file,
    resolve_stream_download_url,
    select_quality_streams,
    target_mismatch_addon_urls,
)


# ── Stage tracker for per-episode progress indicators ────────────────────

class StageTracker:
    """Mutable progress state for one download attempt.

    Carries counters through the search-and-download pipeline so the
    progress renderer can show live T (servers), L (live streams),
    and E (experimental) indicators without deep callback injection
    into the concurrent addon manager.
    """

    def __init__(self) -> None:
        self.server_current: int = 0
        self.server_total: int = 0
        self.live_total: int = 0
        self.live_current: int = 0
        self.experimental_current: int = 0
        self.experimental_total: int = 0
        self._on_update: Callable[[], None] | None = None

    def on_update(self, cb: Callable[[], None]) -> None:
        """Register a no-arg callback invoked on every change."""
        self._on_update = cb

    def _touch(self) -> None:
        if self._on_update:
            self._on_update()

    def set_servers(self, total: int) -> None:
        self.server_total = total
        self._touch()

    def server_done(self, count: int = 1) -> None:
        """Mark *count* addons as having been tested."""
        self.server_current = min(self.server_total, self.server_current + count)
        self._touch()

    def set_live(self, total: int) -> None:
        self.live_total = total
        self.live_current = 0
        self._touch()

    def live_resolved(self, count: int = 1) -> None:
        self.live_current = min(self.live_total, self.live_current + count)
        self._touch()

    def set_experimental(self, total: int) -> None:
        self.experimental_total = total
        self.experimental_current = 0
        self._touch()

    def experimental_done(self, count: int = 1) -> None:
        self.experimental_current = min(self.experimental_total, self.experimental_current + count)
        self._touch()

    def to_dict(self) -> dict[str, int]:
        """Return a flat dict suitable for merging into a progress event."""
        return {
            "server_current": self.server_current,
            "server_total": self.server_total,
            "live_current": self.live_current,
            "live_total": self.live_total,
            "experimental_current": self.experimental_current,
            "experimental_total": self.experimental_total,
        }


def search_and_download(
    title: str,
    imdb_id: str | None = None,
    season: int | None = None,
    episode: int | None = None,
    folder_path: str | None = None,
    preferred_quality: str = "1080p",
    preferred_languages: list[str] | None = None,
    working_addons: list[str] | None = None,
    progress_callback=None,
    bandwidth_limiter=None,
    content_type: str = "auto",
    experimental_addons: list[str] | None = None,
    stage_tracker: StageTracker | None = None,
    skip_full_search: bool = False,
) -> dict:
    """Search addons for a given movie/episode, try to download it.

    For movies, builds one or more search strategies:
      1. IMDB ID (if available) — most accurate
      2. Title-based          — fallback when no IMDB or IMDB fails
    Each strategy is tried in order until one succeeds.
    For series, IMDB is resolved via Cinemeta if not provided.

    ``skip_full_search``: When True and there are no cached working addons,
    skip the full search of all 54+ addons. Used when preflight already
    found zero working addons for this content.
    """
    movie_mode = content_type == "movie" or (content_type == "auto" and not season)

    # Resolve IMDB ID early so it's available for cross-validation
    # in all code paths below (both movie and series strategies).
    effective_imdb = _resolve_imdb_id(title, imdb_id, season)

    if movie_mode:
        id_type = "movie"
        # Build ordered search strategies:
        # 1. IMDB ID (from config or resolved from title)
        # 2. Title-based (fallback when no IMDB known or IMDB search fails)
        strategies: list[tuple[str, str, str]] = []

        # Try to use/provide an IMDB ID — most addons need it for real streams
        if effective_imdb:
            sid = build_stremio_id(effective_imdb, title, None, None)
            strategies.append((sid, "movie", f"IMDB ID {effective_imdb}"))

        # Always include title-based as a fallback (user's requirement — folder name search)
        sid_fallback = build_stremio_id(None, title, None, None)
        if not strategies or strategies[0][0] != sid_fallback:
            strategies.append((sid_fallback, "movie", f"title '{title}'"))
    else:
        id_type = "series"
        strategies: list[tuple[str, str, str]] = []
        # Primary: IMDB-based ID (most accurate for addon lookups)
        if effective_imdb:
            sid = build_stremio_id(effective_imdb, title, season, episode)
            strategies.append((sid, "series", f"series S{season}E{episode} (IMDB)"))
        # Fallback: title-based ID (for addons that don't handle IMDB format)
        sid_fallback = build_stremio_id(None, title, season, episode)
        if not strategies or strategies[0][0] != sid_fallback:
            strategies.append((sid_fallback, "series", f"series S{season}E{episode} (title)"))

    last_result = None
    for stremio_id, current_type, description in strategies:
        result = _search_single_id(
            title=title,
            stremio_id=stremio_id,
            id_type=current_type,
            working_addons=working_addons,
            season=season,
            episode=episode,
            folder_path=folder_path,
            preferred_quality=preferred_quality,
            preferred_languages=preferred_languages,
            progress_callback=progress_callback,
            bandwidth_limiter=bandwidth_limiter,
            stage_tracker=stage_tracker,
            skip_full_search=skip_full_search,
            imdb_id=effective_imdb,
        )
        last_result = result
        if result.get("success"):
            return result

    # ── Experimental addon fallback ────────────────────────────────────
    # If all normal strategies failed and experimental addons are available,
    # try them as a last resort before declaring failure.
    if not last_result or not last_result.get("success"):
        if experimental_addons:
            if stage_tracker:
                stage_tracker.set_experimental(len(experimental_addons))
            exp_result = _try_experimental_addons(
                title=title,
                season=season,
                episode=episode,
                folder_path=folder_path,
                preferred_quality=preferred_quality,
                preferred_languages=preferred_languages,
                progress_callback=progress_callback,
                bandwidth_limiter=bandwidth_limiter,
                experimental_urls=experimental_addons,
                stage_tracker=stage_tracker,
                imdb_id=effective_imdb,
            )
            if exp_result.get("success"):
                return exp_result

    return last_result or {"success": False, "error": "All strategies failed", "working_urls": []}


def _search_single_id(
    title: str,
    stremio_id: str,
    id_type: str,
    working_addons: list[str] | None,
    season: int | None = None,
    episode: int | None = None,
    folder_path: str | None = None,
    preferred_quality: str = "1080p",
    preferred_languages: list[str] | None = None,
    progress_callback=None,
    bandwidth_limiter=None,
    stage_tracker: StageTracker | None = None,
    skip_full_search: bool = False,
    imdb_id: str | None = None,
) -> dict:
    """Search addons for a single identifier and try to download."""

    if working_addons:
        # ── Stage: server scan (cached) ──
        if stage_tracker:
            stage_tracker.set_servers(len(working_addons))

        cached_streams, cached_working_urls = search_working_addons_for_streams(
            id_type,
            stremio_id,
            working_addons,
        )
        cached_result = _try_download_streams(
            title=title,
            streams=cached_streams,
            working_urls=cached_working_urls,
            season=season,
            episode=episode,
            folder_path=folder_path,
            preferred_quality=preferred_quality,
            preferred_languages=preferred_languages,
            progress_callback=progress_callback,
            bandwidth_limiter=bandwidth_limiter,
            imdb_id=imdb_id,
        )
        if cached_result.get("success"):
            return cached_result

        # Mark cached servers as fully scanned
        if stage_tracker:
            stage_tracker.server_done(stage_tracker.server_total)

        remaining_streams, remaining_working_urls = search_remaining_addons_for_streams(
            id_type,
            stremio_id,
            excluded_addons=working_addons,
        )
        combined_working_urls = [*cached_working_urls, *remaining_working_urls]
        if stage_tracker:
            stage_tracker.set_live(len(combined_working_urls))
            stage_tracker.live_resolved(len(combined_working_urls))

        remaining_result = _try_download_streams(
            title=title,
            streams=remaining_streams,
            working_urls=combined_working_urls,
            season=season,
            episode=episode,
            folder_path=folder_path,
            preferred_quality=preferred_quality,
            preferred_languages=preferred_languages,
            progress_callback=progress_callback,
            bandwidth_limiter=bandwidth_limiter,
            imdb_id=imdb_id,
        )
        if remaining_result.get("success"):
            return remaining_result
        if cached_streams or remaining_streams:
            return remaining_result if remaining_streams else cached_result
        return {"success": False, "error": "No streams found", "working_urls": combined_working_urls}

    # No cached addons — search all
    if skip_full_search:
        # Preflight already searched all addons and found nothing for this
        # content.  Skip the full per-episode re-scan to avoid wasting
        # 30+ seconds on every missing episode.
        if stage_tracker:
            stage_tracker.set_servers(0)
            stage_tracker.server_done(0)
            stage_tracker.set_live(0)
            stage_tracker.live_resolved(0)
        return {"success": False, "error": "Preflight found no working addons",
                "working_urls": []}
    streams, working_urls = search_all_addons_for_streams(id_type, stremio_id, working_addons, preferred_languages=preferred_languages)
    if stage_tracker:
        # Mark T complete — we got streams or not
        stage_tracker.set_servers(1)
        stage_tracker.server_done(1)
        # Show how many live addons returned streams
        live_count = len(working_urls) if working_urls else (len(streams) if streams else 0)
        stage_tracker.set_live(max(1, live_count))
        stage_tracker.live_resolved(live_count)
    return _try_download_streams(
        title=title,
        streams=streams,
        working_urls=working_urls,
        season=season,
        episode=episode,
        folder_path=folder_path,
        preferred_quality=preferred_quality,
        preferred_languages=preferred_languages,
        progress_callback=progress_callback,
        bandwidth_limiter=bandwidth_limiter,
        imdb_id=imdb_id,
    )


def _try_download_streams(
    title: str,
    streams: list[StreamInfo],
    working_urls: list[str],
    season: int | None = None,
    episode: int | None = None,
    folder_path: str | None = None,
    preferred_quality: str = "1080p",
    preferred_languages: list[str] | None = None,
    progress_callback=None,
    bandwidth_limiter=None,
    imdb_id: str | None = None,
) -> dict:
    if not streams:
        return {"success": False, "error": "No streams found", "working_urls": working_urls}

    # Always identify addons that returned streams for the wrong show, so
    # they can be proactively blacklisted even when some streams pass
    # filtering but ultimately fail to download.
    all_disabled_urls = target_mismatch_addon_urls(
        streams,
        target_season=season,
        target_episode=episode,
        title=title,
        target_imdb_id=imdb_id,
    )

    streams_to_try = select_quality_streams(
        streams,
        preferred_quality,
        preferred_languages=preferred_languages,
        target_season=season,
        target_episode=episode,
        title=title,
        target_imdb_id=imdb_id,
    )
    if not streams_to_try:
        return {
            "success": False,
            "error": "No downloadable streams found after filtering",
            "working_urls": [],
            "disabled_urls": all_disabled_urls,
            "permanent_failure": True,
        }

    last_error = None
    invalid_download_errors = 0
    attempted_downloads = 0
    transient_download_errors = 0
    for index, stream in enumerate(streams_to_try):
        download_url = resolve_stream_download_url(stream)
        if not download_url:
            continue

        attempted_downloads += 1
        if settings.DRY_RUN:
            return {
                "success": True,
                "filename": build_media_filename(title, season, episode),
                "quality": stream.name,
                "provider": "stremio-dry-run",
                "working_urls": working_urls,
                "successful_url": stream.addon_url,
            }

        filename = build_media_filename(title, season, episode, folder_path)
        import threading
        thread_id = threading.get_ident()
        try:
            download_stream_to_file(
                download_url,
                filename,
                progress_callback=progress_callback,
                bandwidth_limiter=bandwidth_limiter,
                thread_id=thread_id,
                stall_timeout=settings.DOWNLOAD_STALL_TIMEOUT,
            )
            return _success_result(filename, stream, working_urls)
        except InvalidVideoDownloadError as e:
            invalid_download_errors += 1
            from py_stremio.components.errors.error_logger import log_error

            log_error(f"invalid_video({stream.addon_name})", e, stream.url or stream.info_hash or "?")
            if can_retry_with_debrid(stream, download_url):
                retry_result = _retry_with_real_debrid(stream, filename, working_urls, progress_callback=progress_callback, bandwidth_limiter=bandwidth_limiter)
                if retry_result:
                    return retry_result
            last_error = str(e)
        except StreamStallError as e:
            # The download started but stalled (no bytes for 60s+).  This
            # typically means the local torrent proxy can't find peers
            # yet (brand-new episode).  Do NOT retry with RealDebrid on
            # the same info hash — RD has the same peer-discovery delay.
            # Move on to the next stream in the queue.
            transient_download_errors += 1
            from py_stremio.components.errors.error_logger import log_error

            log_error(
                f"stalled_download({stream.addon_name})",
                e,
                stream.url or stream.info_hash or "?",
            )
            last_error = str(e)
            continue
        except Exception as e:
            transient_download_errors += 1
            from py_stremio.components.errors.error_logger import log_error

            log_error(f"download_stream({stream.addon_name})", e, stream.url or stream.info_hash or "?")
            if can_retry_with_debrid(stream, download_url):
                retry_result = _retry_with_real_debrid(stream, filename, working_urls, progress_callback=progress_callback, bandwidth_limiter=bandwidth_limiter)
                if retry_result:
                    return retry_result
            last_error = str(e)

    permanent_failure = (
        attempted_downloads > 0
        and invalid_download_errors == attempted_downloads
        and transient_download_errors == 0
    )
    return {
        "success": False,
        "error": f"All streams failed. Last error: {last_error}",
        "working_urls": working_urls,
        "disabled_urls": all_disabled_urls,
        "permanent_failure": permanent_failure,
    }


def _resolve_imdb_id(title: str, imdb_id: str | None, season: int | None) -> str | None:
    if not imdb_id:
        imdb_id = get_series_imdb_id(title, season) if season else get_imdb_id(title)

    if not imdb_id:
        return None

    return imdb_id


def _retry_with_real_debrid(stream: StreamInfo, filename: str, working_urls: list[str], progress_callback=None, bandwidth_limiter=None) -> dict | None:
    if not stream.info_hash:
        return None

    rd_url = resolve_torrent_with_debrid(stream.info_hash, stream.file_idx)
    if not rd_url:
        return None

    import threading
    thread_id = threading.get_ident()

    try:
        download_stream_to_file(rd_url, filename, progress_callback=progress_callback, bandwidth_limiter=bandwidth_limiter, thread_id=thread_id)
        return _success_result(filename, stream, working_urls)
    except Exception as e:
        from py_stremio.components.errors.error_logger import log_error

        log_error(f"realdebrid_download({stream.addon_name})", e, stream.url or stream.info_hash or "?")
        return None


def _success_result(filename: str, stream: StreamInfo, working_urls: list[str]) -> dict:
    return {
        "success": True,
        "filename": filename,
        "quality": stream.name,
        "addon_name": getattr(stream, "addon_name", ""),
        "working_urls": working_urls,
        "successful_url": getattr(stream, "addon_url", None),
    }


# ── Experimental addon fallback ─────────────────────────────────────────

def _try_experimental_addons(
    title: str,
    season: int | None = None,
    episode: int | None = None,
    folder_path: str | None = None,
    preferred_quality: str = "1080p",
    preferred_languages: list[str] | None = None,
    progress_callback=None,
    bandwidth_limiter=None,
    experimental_urls: list[str] | None = None,
    stage_tracker: StageTracker | None = None,
    imdb_id: str | None = None,
) -> dict:
    """Query experimental addons and attempt download for one episode.

    Called only when all normal addon strategies have already failed.
    Builds a simple Stremio ID per episode and tries to resolve/download.
    """
    if not experimental_urls:
        return {"success": False, "error": "No experimental addons", "working_urls": []}

    mgr = ExperimentalAddonManager(experimental_urls)
    stremio_id = build_stremio_id(None, title, season, episode)
    if not stremio_id:
        return {"success": False, "error": "Could not build Stremio ID", "working_urls": []}

    type_ = "series" if season is not None else "movie"

    streams, exp_working_urls = mgr.search(type_, stremio_id)
    if stage_tracker:
        stage_tracker.experimental_done(len(experimental_urls))
    if not streams:
        return {"success": False, "error": "No experimental streams found", "working_urls": []}

    return _try_download_streams(
        title=title,
        streams=streams,
        working_urls=exp_working_urls,
        season=season,
        episode=episode,
        folder_path=folder_path,
        preferred_quality=preferred_quality,
        preferred_languages=preferred_languages,
        progress_callback=progress_callback,
        bandwidth_limiter=bandwidth_limiter,
        imdb_id=imdb_id,
    )
