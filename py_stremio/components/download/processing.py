"""Process configured series and movie folders."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
import threading
import time
from typing import Any, Callable

from py_stremio.components.configs.config_file import load_config, save_config, DownloadConfig
from py_stremio.components.library.media_file import detect_existing_season_episodes, iter_video_files, scan_episode_files
from py_stremio.components.reports.output_writer import suppress_current_thread_output
from py_stremio.components.configs.app_settings import settings
from py_stremio.components.state.app_state import load_state, save_state, DownloadState
from py_stremio.components.stremio.stremio_client import StageTracker, search_and_download
from py_stremio.utils.cancellation import (
    DownloadCancelled,
    raise_if_shutdown_requested,
    request_shutdown,
    shutdown_executor_now,
    shutdown_requested,
)
from py_stremio.components.download.stream_download import build_media_filename, _minimum_completed_video_bytes
from py_stremio.components.stremio.stremio_url import normalize_manifest_url, unique_manifest_urls
from py_stremio.components.addons.addon_search_service import preflight_discover_working_addons
from py_stremio.components.stremio.stremio_ids import build_stremio_id
from py_stremio.components.addons.experimental import load_experimental_urls

# Module-level flag to print the experimental addon count once, not per-folder
_experimental_announced: list[bool] = [False]


# ── Task descriptor for global thread pool scheduling ────────────────────


@dataclass
class SeasonFolderTask:
    """Prepared context for one season folder ready to download episodes."""
    folder_path: Path
    config_path: Path
    config: DownloadConfig
    state: DownloadState
    title: str
    season: int
    quality: str
    preferred_languages: list[str] | None
    servers: list[str]
    experimental_addons: list[str] | None
    missing_episodes: list[int]
    total_missing: int
    bandwidth_limiter: Any = None
    servers_lock: threading.Lock = field(default_factory=threading.Lock)
    config_lock: threading.Lock = field(default_factory=threading.Lock)
    progress_lock: threading.Lock = field(default_factory=threading.Lock)
    worker_semaphore: threading.Semaphore | None = None
    quiet_output: bool = False
    # Accumulated results (mutated in place as episodes complete)
    downloaded: int = 0
    failed: int = 0
    skipped: int = 0
    verified_servers: list[str] = field(default_factory=list)
    # When True, preflight searched all addons and found zero working addons —
    # skip the full per-episode addon search to avoid re-searching all
    # 54 addons for every single missing episode.
    no_working_addons: bool = False


@dataclass
class MovieFolderTask:
    """Prepared context for one movie folder ready to download."""
    folder_path: Path
    config_path: Path
    config: DownloadConfig
    state: DownloadState
    title: str
    quality: str
    preferred_languages: list[str] | None
    servers: list[str]
    experimental_addons: list[str] | None
    bandwidth_limiter: Any = None
    quiet_output: bool = False


def scan_folder_for_episodes(folder_path: Path) -> list[dict]:
    """Scan folder and return episode file info dictionaries."""
    return [
        {
            "path": media_file.path,
            "filename": media_file.filename,
            "episode": media_file.episode,
        }
        for media_file in scan_episode_files(folder_path)
    ]


def _save_verified_server_urls(config, config_path: Path, urls: list[str] | None) -> list[str]:
    """Replace the server cache with URLs verified by a successful download.

    The cache is only cleared at the end of a run where missing items were
    attempted and no download succeeded. A single failed episode must not wipe
    the existing cache while later episodes in the same run may still succeed.
    """
    servers = unique_manifest_urls(urls)

    if servers != unique_manifest_urls(config.servers):
        config.servers = servers
        save_config(config_path, config)
        if servers:
            print(f"  Saved {len(servers)} verified download servers to config")
        else:
            print("  Cleared server cache; no addon completed a download")

    return servers


def setup_season_folder(
    folder_path: Path,
    bandwidth_limiter=None,
    quiet_output: bool = False,
) -> SeasonFolderTask | None:
    """Prepare a season folder for download — load config, scan, pre-flight.

    Returns a ``SeasonFolderTask`` with all state needed to download episodes,
    or ``None`` if the folder should be skipped (disabled, invalid, complete).
    """
    config, config_path = load_config(folder_path)
    state = load_state(folder_path)

    if not config.enabled:
        print(f"    skipped ({folder_path.parent.name} S{config.season or 1:02d} disabled)")
        return None

    _update_disabled_servers(state, config, config_path, folder_path)

    if not config.title:
        return None
    title = config.title

    season = config.season if config.season is not None else 1
    if config.episode_count is None:
        return None

    # ── Experimental addons ──────────────────────────────────────────
    experimental_addons: list[str] | None = None
    if config.experimental_addons_enabled:
        experimental_addons = load_experimental_urls()
        if experimental_addons and not _experimental_announced[0]:
            _experimental_announced[0] = True
            print(f"    \U0001f9ea {len(experimental_addons)} experimental addon(s) loaded")

    quality = _preferred_quality(config)
    preferred_languages = _preferred_languages(config)

    existing_episodes = detect_existing_season_episodes(folder_path, config.episode_count)
    start_episode = max(1, config.current_episode_download or 1)
    missing = _missing_episodes(folder_path, config, state, season, existing_episodes)

    if missing:
        _set_current_episode(config, config_path, missing[0])
    elif start_episode <= (config.episode_count or 1) and config.available_episodes is None:
        _set_current_episode(config, config_path, (config.episode_count or 1) + 1)

    # ── Pre-flight addon discovery ───────────────────────────────────
    servers = unique_manifest_urls(config.servers)
    disabled = set(unique_manifest_urls(config.disabled_servers))
    if disabled:
        filtered = [s for s in servers if s not in disabled]
        if len(filtered) < len(servers):
            servers = filtered
    no_working_addons = False
    if missing and not servers and config.imdb_id:
        first_episode = missing[0]
        stremio_id = build_stremio_id(config.imdb_id, title, season, first_episode)
        discovered = preflight_discover_working_addons(
            "series",
            stremio_id,
            title=title,
            season=season,
            episode=first_episode,
            imdb_id=config.imdb_id,
        )
        if discovered:
            servers = discovered
            if not quiet_output:
                print(f"      Using {len(discovered)} preflight addon candidate(s)")
        else:
            if not quiet_output:
                print(f"      No working addons found — skipping repeated per-episode searches")

        no_working_addons = len(discovered) == 0
    elif not servers and missing:
        if not quiet_output:
            print(f"      No server cache and no IMDB ID — will search all per-episode")
        no_working_addons = False

    return SeasonFolderTask(
        folder_path=folder_path,
        config_path=config_path,
        config=config,
        state=state,
        title=title,
        season=season,
        quality=quality,
        preferred_languages=preferred_languages,
        servers=servers,
        experimental_addons=experimental_addons,
        missing_episodes=missing,
        total_missing=len(missing),
        bandwidth_limiter=bandwidth_limiter,
        quiet_output=quiet_output,
        no_working_addons=no_working_addons,
    )


def download_episode_task(
    task: SeasonFolderTask,
    index: int,
    episode_num: int,
    progress_callback: Callable | None = None,
) -> dict:
    """Download a single episode from a prepared ``SeasonFolderTask``.

    ``index`` is the 1-based position within the task's missing_episodes list
    (used for progress display).  Returns the same dict as the inner
    ``download_episode`` closure.
    """
    return _do_download_one_episode(task, index, episode_num, progress_callback)


def _do_download_one_episode(
    task: SeasonFolderTask,
    index: int,
    episode_num: int,
    progress_callback: Callable | None = None,
) -> dict:
    """Download one episode from a prepared task — extracted logic."""
    # Final safety net: never attempt a network download for an episode whose
    # generated final filename already exists on disk. This protects against
    # stale tasks or stale missing-episode lists created before state/config was
    # reconciled.
    generated_filename = _generated_episode_filename(task.folder_path, task.config, task.season, episode_num)
    if (task.folder_path / generated_filename).exists():
        # Validate existing file before skipping: if it's too small, it's
        # likely an incomplete download from a previous failed run and must
        # be re-downloaded instead of silently skipped.
        existing_path = task.folder_path / generated_filename
        existing_size = existing_path.stat().st_size
        min_bytes = _minimum_completed_video_bytes()
        if min_bytes > 0 and existing_size < min_bytes:
            print(f"    S{task.season:02d}E{episode_num:02d}: existing file "
                  f"is only {existing_size / 1024 / 1024:.1f} MB "
                  f"(min {min_bytes / 1024 / 1024:.0f} MB) — re-downloading")
            existing_path.unlink(missing_ok=True)
        else:
            if not task.state.is_downloaded(generated_filename):
                task.state.add_download(generated_filename, task.quality, "stremio")
            return {
                "episode": episode_num,
                "result": {
                    "success": False,
                    "skipped": True,
                    "reason": "already exists",
                    "filename": generated_filename,
                    "working_urls": [],
                },
            }

    last_downloaded_bytes = 0
    last_total_bytes = 0
    last_rate_bps = 0.0
    last_progress_bytes: int | None = None
    last_progress_at: float | None = None
    last_bytes_event: dict = {}
    stage_tracker = StageTracker()

    def emit(event: dict) -> None:
        if progress_callback:
            with task.progress_lock:
                progress_callback(event)

    # Core identity fields that must always reach the progress renderer
    _identity_fields = {
        "title": task.title,
        "season": task.season,
        "episode": episode_num,
        "current": index,
        "total": task.total_missing,
    }

    emit({
        "type": "episode_start",
        **_identity_fields,
        **stage_tracker.to_dict(),
    })

    def _emit_with_stage() -> None:
        # Always carry identity fields (title, season, episode, position)
        # even when last_bytes_event has not been set yet (pre-bytes stage
        # events from the addon search pipeline).
        payload = {
            **last_bytes_event,
            **stage_tracker.to_dict(),
        }
        for k in ("title", "season", "episode", "current", "total"):
            if k not in payload or payload[k] is None:
                payload[k] = _identity_fields.get(k)
        if payload:
            emit(payload)

    stage_tracker.on_update(_emit_with_stage)

    def on_bytes(downloaded_bytes: int, total_bytes: int) -> None:
        nonlocal last_downloaded_bytes, last_total_bytes, last_rate_bps, last_progress_bytes, last_progress_at, last_bytes_event
        now = time.monotonic()
        if last_progress_bytes is None or downloaded_bytes < last_progress_bytes:
            last_rate_bps = 0.0
            last_progress_bytes = downloaded_bytes
            last_progress_at = now
        else:
            elapsed = max(0.001, now - (last_progress_at or now))
            delta = downloaded_bytes - last_progress_bytes
            last_rate_bps = delta / elapsed if delta else 0.0
            last_progress_bytes = downloaded_bytes
            last_progress_at = now
        last_downloaded_bytes = downloaded_bytes
        last_total_bytes = total_bytes
        last_bytes_event = {
            "type": "bytes",
            "title": task.title,
            "season": task.season,
            "episode": episode_num,
            "current": index,
            "total": task.total_missing,
            "downloaded": downloaded_bytes,
            "bytes_total": total_bytes,
            "rate_bps": last_rate_bps,
            **stage_tracker.to_dict(),
        }
        emit(last_bytes_event)

    # Guard against previously-downloaded-but-deleted files
    generated_filename = _generated_episode_filename(task.folder_path, task.config, task.season, episode_num)
    legacy_key = f"episode_{episode_num}.mkv"
    bad_servers: list[str] = []
    for state_key in (generated_filename, legacy_key):
        if task.state.is_downloaded(state_key):
            previous_url = task.state.get_server(state_key)
            if previous_url:
                bad_servers.append(previous_url)
    if bad_servers:
        with task.config_lock:
            new_disabled = unique_manifest_urls(bad_servers + task.config.disabled_servers)
            if new_disabled != unique_manifest_urls(task.config.disabled_servers):
                task.config.disabled_servers = new_disabled
                save_config(task.config_path, task.config)
    active_servers = [s for s in task.servers if s not in bad_servers]

    # Preflight has already searched every configured addon for this exact
    # show/season/episode. With no usable result, another full search for every
    # missing episode only multiplies timeouts and rate-limit cooldowns.
    skip_full = task.no_working_addons

    result: dict[str, Any] = {}
    error: BaseException | None = None
    try:
        raise_if_shutdown_requested()
        result = search_and_download(
            title=task.title,
            imdb_id=task.config.imdb_id,
            season=task.season,
            episode=episode_num,
            folder_path=str(task.folder_path),
            preferred_quality=task.quality,
            preferred_languages=task.preferred_languages,
            working_addons=active_servers,
            progress_callback=on_bytes,
            bandwidth_limiter=task.bandwidth_limiter,
            experimental_addons=task.experimental_addons,
            stage_tracker=stage_tracker,
            skip_full_search=skip_full,
            quality_fallbacks=(
                task.config.quality.fallbacks if task.config.quality else None
            ),
            allow_higher=(
                task.config.quality.allow_higher if task.config.quality else False
            ),
            allow_lower=(
                task.config.quality.allow_lower if task.config.quality else True
            ),
        )
    except BaseException as exc:
        error = exc
        raise
    finally:
        cancelled = isinstance(error, (DownloadCancelled, KeyboardInterrupt)) or shutdown_requested()
        emit({
            "type": "episode_done",
            **_identity_fields,
            "success": bool(result.get("success")),
            "outcome": "cancelled" if cancelled else ("downloaded" if result.get("success") else "failed"),
            "reason": "interrupted" if cancelled else (str(error) if error else result.get("error")),
            "downloaded": last_downloaded_bytes,
            "bytes_total": last_total_bytes,
            "rate_bps": 0.0,
        })

    return {"episode": episode_num, "result": result}


# ── Helpers ──────────────────────────────────────────────────────────


def _update_disabled_servers(
    state,
    config,
    config_path: Path,
    folder_path: Path,
) -> list[str]:
    """Scan all state entries for missing files and persist their servers as disabled.

    When a file was downloaded but the user manually deleted it, that means
    the server delivered wrong content (e.g. South Park instead of One Piece).
    That server is added to config.disabled_servers so it is never queried
    again for this series folder.
    """
    new_disabled: list[str] = []
    for filename, record in state.items.items():
        if not record.server and not record.addon_url:
            continue
        server_url = record.server or record.addon_url
        file_path = folder_path / filename
        if not file_path.exists():
            new_disabled.append(server_url)

    if not new_disabled:
        return unique_manifest_urls(config.disabled_servers)

    current = set(unique_manifest_urls(config.disabled_servers))
    updated = set(unique_manifest_urls(new_disabled))
    if not updated - current:
        return unique_manifest_urls(config.disabled_servers)

    combined = unique_manifest_urls(new_disabled + config.disabled_servers)
    config.disabled_servers = combined
    save_config(config_path, config)
    return combined


def _verified_urls_from_result(result: dict) -> list[str]:
    """Return addon URLs worth saving after a successful download.

    Prefer the exact addon that produced the downloaded stream. If older/mocked
    call paths do not include it, fall back to the addons that returned streams
    in the same search only because a download did complete in that search.
    """
    successful_url = normalize_manifest_url(result.get("successful_url"))
    if successful_url:
        return [successful_url]
    return unique_manifest_urls(result.get("working_urls"))


def _preferred_quality(config) -> str:
    return config.quality.preferred if config.quality else "1080p"


def _preferred_languages(config) -> list[str] | None:
    if config.languages:
        return list(config.languages)
    if config.language and config.language.lower() != "any":
        return [config.language]
    return None


def _set_current_episode(config, config_path: Path, episode: int) -> None:
    next_episode = max(1, episode)
    if config.current_episode_download == next_episode:
        return
    config.current_episode_download = next_episode
    save_config(config_path, config)


def _generated_episode_filename(folder_path: Path, config, season: int, episode: int) -> str:
    return Path(build_media_filename(config.title, season, episode, str(folder_path))).name


def _movie_target_path(folder_path: Path, config) -> Path:
    """Return the absolute path of the expected final movie file.

    Uses the configured title (preferred) or the folder name as a
    fallback, matching the ``build_media_filename`` output used by the
    download path so the two halves of the pipeline agree on the
    expected output location.
    """
    title = config.title or folder_path.name
    return folder_path / f"{title}.mkv"


def _movie_partial_path(folder_path: Path, config) -> Path:
    """Return the absolute path of the in-progress ``.part`` movie file, if any.

    The downloader writes bytes to ``<title>.mkv.part`` while a download
    is running and atomically renames it to ``<title>.mkv`` on success.
    Detecting the ``.part`` file is what lets the pipeline announce
    "resuming partial download" instead of pretending the search is a
    fresh start.
    """
    return _movie_target_path(folder_path, config).with_suffix(".mkv.part")


def _is_completed_generated_file(folder_path: Path, config, season: int, episode: int) -> bool:
    """Return True when the final generated media file is already present."""
    expected = _generated_episode_filename(folder_path, config, season, episode)
    return (folder_path / expected).exists()


def _maybe_convert_tiny_untracked_file_to_partial(folder_path: Path, config, season: int, episode: int, state) -> bool:
    """Move suspicious tiny final files to .part so interrupted legacy downloads can resume."""
    expected = _generated_episode_filename(folder_path, config, season, episode)
    final_path = folder_path / expected
    if not final_path.exists() or state.is_downloaded(expected):
        return False

    min_mb = getattr(settings, "MIN_COMPLETED_VIDEO_SIZE_MB", 100)
    if min_mb <= 0:
        return False

    min_bytes = min_mb * 1024 * 1024
    if final_path.stat().st_size >= min_bytes:
        return False

    partial_path = folder_path / f"{expected}.part"
    if not partial_path.exists():
        final_path.replace(partial_path)
    return True


def _is_resume_candidate(folder_path: Path, config, season: int, episode: int, state) -> bool:
    """Return True when a .part download exists but was not marked complete."""
    expected = _generated_episode_filename(folder_path, config, season, episode)
    return (folder_path / f"{expected}.part").exists() and not state.is_downloaded(expected)


def _missing_episodes(folder_path: Path, config, state, season: int, existing_episodes: set[int]) -> list[int]:
    final_episode = config.episode_count or 20
    start_episode = max(1, config.current_episode_download or 1)
    # When current_episode_download has been advanced past the season's
    # final episode, all episodes were already attempted.  Reset to 1 so
    # the scan can still detect files that were deleted from disk since
    # the last successful run.
    if start_episode > final_episode:
        start_episode = 1
    missing = []
    # ── Stale-history scan ───────────────────────────────────────────────────
    # Episodes before the cursor are never re-examined, even when the file
    # was deleted after a successful download.  Scan them for mismatches:
    # state says downloaded but file is gone → re-add to missing.
    # A genuine miss (neither state nor file) also gets picked up.
    for episode in range(1, start_episode):
        generated_filename = _generated_episode_filename(folder_path, config, season, episode)
        if state.is_downloaded(generated_filename):
            final_path = folder_path / generated_filename
            if not final_path.exists():
                print(f"    State marks S{season:02d}E{episode:02d} downloaded but file "
                      f"missing — re-downloading")
                missing.append(episode)
            continue  # on-disk file exists → skip
        # Not in state at all — check disk directly
        if episode in existing_episodes or _is_completed_generated_file(folder_path, config, season, episode):
            continue
        missing.append(episode)
    if config.available_episodes is not None:
        candidates = [
            int(episode)
            for episode in config.available_episodes
            if int(episode) >= start_episode and int(episode) <= final_episode
        ]
    else:
        candidates = list(range(start_episode, final_episode + 1))
    for episode in candidates:
        generated_filename = _generated_episode_filename(folder_path, config, season, episode)
        legacy_key = f"episode_{episode}.mkv"
        if state.is_downloaded(legacy_key) or state.is_downloaded(generated_filename):
            # State says downloaded, but verify the file actually exists on disk.
            # If the user moved/removed files, treat as missing.
            final_path = folder_path / generated_filename
            if not final_path.exists():
                print(f"    State marks S{season:02d}E{episode:02d} downloaded but file "
                      f"missing — re-downloading")
                missing.append(episode)
                continue
            continue
        if _maybe_convert_tiny_untracked_file_to_partial(folder_path, config, season, episode, state):
            missing.append(episode)
            continue
        if episode in existing_episodes or _is_completed_generated_file(folder_path, config, season, episode):
            continue
        if _is_resume_candidate(folder_path, config, season, episode, state):
            missing.append(episode)
            continue
        missing.append(episode)
    if settings.LIMIT_EPISODES > 0:
        missing = missing[:settings.LIMIT_EPISODES]
    return missing


def _drop_existing_episodes_from_task(task: SeasonFolderTask) -> int:
    """Remove episodes whose generated final file already exists from a task.

    This is a scheduler-level safety net for stale prepared tasks. It keeps
    progress counters honest by reindexing the remaining queue after existing
    files are dropped, instead of letting E05 render as position 5/8 when
    E01-E04 already exist.
    """
    remaining: list[int] = []
    skipped = 0
    for episode in task.missing_episodes:
        generated_filename = _generated_episode_filename(task.folder_path, task.config, task.season, episode)
        if (task.folder_path / generated_filename).exists():
            if not task.state.is_downloaded(generated_filename):
                task.state.add_download(generated_filename, task.quality, "stremio")
            skipped += 1
        else:
            remaining.append(episode)
    if remaining != task.missing_episodes:
        task.missing_episodes = remaining
        task.total_missing = len(remaining)
    return skipped


# ── Backward-compatible season folder processor ────────────────────


def process_season_folder(
    folder_path: Path,
    progress_callback=None,
    max_workers: int = 1,
    bandwidth_limiter=None,
    worker_semaphore: threading.Semaphore | None = None,
    quiet_output: bool = False,
    live_configs: list | None = None,
) -> dict:
    """Process a season folder — backward-compatible wrapper around the task system.

    When ``live_configs`` is provided, the loaded ``task.config`` is
    appended to it so the caller can observe and mutate quality
    settings live (for example the bottom-bar 4K toggle in the
    interactive UI).  The on-disk config is never written by this
    function for the 4K toggle — it is a session-only override.
    """
    task = setup_season_folder(
        folder_path=folder_path,
        bandwidth_limiter=bandwidth_limiter,
        quiet_output=quiet_output,
    )
    if task is None:
        return {"skipped": True, "reason": "setup returned no task"}

    if live_configs is not None:
        live_configs.append(task.config)

    skipped_existing = _drop_existing_episodes_from_task(task)
    if skipped_existing:
        save_state(folder_path, task.state)

    if not task.missing_episodes:
        episodes = scan_folder_for_episodes(folder_path)
        for ep in episodes:
            if ep["path"].exists() and not task.state.is_downloaded(ep["filename"]):
                task.state.add_download(ep["filename"], task.quality, "stremio")
                task.skipped += 1
        save_state(folder_path, task.state)
        return {"downloaded": 0, "skipped": task.skipped + skipped_existing, "failed": 0}

    downloaded = 0
    skipped = skipped_existing
    failed = 0
    failed_reasons: list[str] = []
    verified_servers: list[str] = []
    servers_lock = threading.Lock()
    config_lock = threading.Lock()
    progress_lock = threading.Lock()
    total_missing = task.total_missing
    missing = task.missing_episodes

    def emit(event: dict) -> None:
        if progress_callback:
            with progress_lock:
                progress_callback(event)

    def _download_episode_with_slot(index: int, episode_num: int) -> dict:
        if worker_semaphore:
            acquired = worker_semaphore.acquire()
            if acquired is False:
                raise DownloadCancelled()
        try:
            if quiet_output:
                with suppress_current_thread_output():
                    return _do_download_one_episode(task, index, episode_num, progress_callback)
            return _do_download_one_episode(task, index, episode_num, progress_callback)
        finally:
            if worker_semaphore:
                worker_semaphore.release()

    def apply_result(episode_num: int, result: dict, completed_successes: set[int] | None = None) -> None:
        nonlocal downloaded, failed, verified_servers
        if result.get("success"):
            filename = Path(result.get("filename", f"episode_{episode_num}.mkv")).name
            server = result.get("successful_url") or ""
            task.state.add_download(filename, result.get("quality", task.quality), "stremio", server=server)
            save_state(folder_path, task.state)
            downloaded += 1
            successful_urls = _verified_urls_from_result(result)
            for successful_url in successful_urls:
                if successful_url and successful_url not in verified_servers:
                    verified_servers.append(successful_url)
            with servers_lock:
                task.servers = _save_verified_server_urls(task.config, task.config_path, verified_servers)
            if completed_successes is not None:
                completed_successes.add(episode_num)
                next_cursor = min((ep for ep in missing if ep not in completed_successes), default=max(missing) + 1)
                _set_current_episode(task.config, task.config_path, next_cursor)
            else:
                _set_current_episode(task.config, task.config_path, episode_num + 1)
        else:
            disabled_urls = unique_manifest_urls(result.get("disabled_urls"))
            if disabled_urls:
                with config_lock:
                    new_disabled = unique_manifest_urls(disabled_urls + task.config.disabled_servers)
                    if new_disabled != unique_manifest_urls(task.config.disabled_servers):
                        task.config.disabled_servers = new_disabled
                        save_config(task.config_path, task.config)
                with servers_lock:
                    disabled_set = set(new_disabled)
                    task.servers = [s for s in task.servers if s not in disabled_set]
            failure_reason = result.get("error", "failed")
            task.state.mark_failed(f"episode_{episode_num}", failure_reason, 1)
            failed_reasons.append(f"S{task.season:02d}E{episode_num:02d}: {failure_reason}")
            failed += 1

    max_attempts = getattr(settings, "MAX_DOWNLOAD_ATTEMPTS", 5)
    queue = deque(missing)
    completed_successes: set[int] = set()

    if max_workers > 1 and total_missing > 1:
        for round_num in range(max_attempts):
            if shutdown_requested() or not queue:
                break
            round_items = list(queue)
            queue.clear()
            if round_num == 0:
                print(f"  Downloading {len(round_items)} episodes")
            elif len(round_items) > 1:
                pass  # silently retry deferred episodes
            executor = ThreadPoolExecutor(max_workers=max(1, max_workers))
            futures = []
            try:
                futures = [
                    executor.submit(_download_episode_with_slot, idx, ep_num)
                    for idx, ep_num in enumerate(round_items, start=1)
                ]
                future_map = {future: ep_num for future, ep_num in zip(futures, round_items)}
                deferred: set[int] = set()
                for future in as_completed(future_map):
                    if shutdown_requested():
                        shutdown_executor_now(executor, futures)
                        break
                    item = future.result()
                    if item["result"].get("success"):
                        apply_result(item["episode"], item["result"], completed_successes)
                    elif item["result"].get("permanent_failure"):
                        apply_result(item["episode"], item["result"])
                    else:
                        deferred.add(item["episode"])
                queue.extend(ep_num for ep_num in round_items if ep_num in deferred)
            except KeyboardInterrupt:
                request_shutdown()
                shutdown_executor_now(executor, futures)
                raise
            else:
                if shutdown_requested():
                    shutdown_executor_now(executor, futures)
                else:
                    executor.shutdown(wait=True)
    else:
        for round_num in range(max_attempts):
            if shutdown_requested() or not queue:
                break
            round_items = list(queue)
            queue.clear()
            if round_num > 0:
                pass  # silently retry deferred episodes
            for index, episode_num in enumerate(round_items, start=1):
                if shutdown_requested():
                    queue.extend(round_items[index - 1:])
                    break
                _set_current_episode(task.config, task.config_path, episode_num)
                item = _download_episode_with_slot(index, episode_num)
                if item["result"].get("success"):
                    apply_result(item["episode"], item["result"])
                elif item["result"].get("permanent_failure"):
                    apply_result(item["episode"], item["result"])
                else:
                    queue.append(episode_num)

    if not shutdown_requested():
        for episode_num in queue:
            reason = "All retry rounds exhausted"
            task.state.mark_failed(f"episode_{episode_num}", reason, max_attempts)
            failed_reasons.append(f"S{task.season:02d}E{episode_num:02d}: {reason}")
            failed += 1

    if task.missing_episodes:
        with servers_lock:
            task.servers = _save_verified_server_urls(task.config, task.config_path, verified_servers)

    episodes = scan_folder_for_episodes(folder_path)
    for ep in episodes:
        if ep["path"].exists() and not task.state.is_downloaded(ep["filename"]):
            task.state.add_download(ep["filename"], task.quality, "stremio")
            skipped += 1
    save_state(folder_path, task.state)
    return {
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "cancelled": len(queue) if shutdown_requested() else 0,
        "failed_reasons": failed_reasons,
    }


# ── Movie folder processing ────────────────────────────────────────


def process_movie_folder(
    folder_path: Path,
    progress_callback=None,
    bandwidth_limiter=None,
    live_configs: list | None = None,
) -> dict:
    """Process a movie folder and download missing content from Stremio.

    When ``live_configs`` is provided, the loaded ``config`` is
    appended to it so the caller can observe and mutate quality
    settings live (for example the bottom-bar 4K toggle in the
    interactive UI).  The on-disk config is never written by this
    function for the 4K toggle — it is a session-only override.
    """
    config, config_path = load_config(folder_path)
    state = load_state(folder_path)
    if live_configs is not None:
        live_configs.append(config)

    # ── Load experimental addons (last-resort fallback) ─────────────────
    experimental_addons: list[str] | None = None
    if config.experimental_addons_enabled:
        experimental_addons = load_experimental_urls()
        if experimental_addons:
            print(f"  \U0001f9ea {len(experimental_addons)} experimental addon(s) loaded (last-resort)")

    if not config.enabled:
        return {"skipped": True, "reason": "disabled"}

    # ── Disabled-server cleanup ────────────────────────────────────────
    _update_disabled_servers(state, config, config_path, folder_path)

    # Movies don't use episode tracking — clear it if somehow set
    if config.current_episode_download != 0:
        config.current_episode_download = 0
        save_config(config_path, config)

    video_files = iter_video_files(folder_path)
    quality = _preferred_quality(config)

    if video_files:
        for file_path in video_files:
            if not state.is_downloaded(file_path.name):
                state.add_download(file_path.name, quality, "stremio")
        save_state(folder_path, state)
        return {"downloaded": 0, "skipped": len(video_files)}

    # ── Partial download detection ──────────────────────────────────────
    # If a ``.part`` file exists from a previous interrupted download,
    # surface that to the user BEFORE the (potentially slow) addon
    # search starts so they know the system is aware of the partial
    # bytes.  The actual resume happens inside ``download_stream_to_file``
    # via HTTP Range headers — once a stream is selected, the partial
    # file is appended to instead of being rewritten from zero.
    partial_path = _movie_partial_path(folder_path, config)
    resume_state: dict[str, Any] = {"partial_bytes": 0}
    if partial_path.exists():
        try:
            partial_bytes = partial_path.stat().st_size
        except OSError:
            partial_bytes = 0
        if partial_bytes > 0:
            resume_state["partial_bytes"] = partial_bytes
            size_mb = partial_bytes / (1024 * 1024)
            size_gb = size_mb / 1024
            human = f"{size_gb:.1f} GB" if size_gb >= 1 else f"{size_mb:.0f} MB"
            print(
                f"  ↻ Resuming partial download: {partial_path.name} "
                f"({human} already on disk) — search will reuse the bytes via HTTP Range"
            )

    title = config.search_group or config.title or folder_path.name
    servers = unique_manifest_urls(config.servers)
    disabled = set(unique_manifest_urls(config.disabled_servers))
    if disabled:
        servers = [s for s in servers if s not in disabled]
    preferred_languages = _preferred_languages(config)

    # Pre-flight addon discovery for movies
    stremio_id = build_stremio_id(config.imdb_id, title, None, None) if config.imdb_id else build_stremio_id(None, title, None, None)
    if not servers:
        discovered = preflight_discover_working_addons("movie", stremio_id)
        if discovered:
            servers = discovered
        else:
            pass

    movie_stage_tracker = StageTracker()
    movie_progress_lock = threading.Lock()
    movie_last_downloaded = 0
    movie_last_total = 0
    movie_last_progress_bytes: int | None = None
    movie_last_progress_at: float | None = None
    movie_rate_bps = 0.0
    # Seed with title so stage-only events show the movie name
    movie_last_bytes: dict = {
        "type": "episode_start",
        "title": title,
        "season": None,
        "episode": None,
        "current": 1,
        "total": 1,
    }

    def _movie_emit_stage() -> None:
        if progress_callback:
            with movie_progress_lock:
                progress_callback({**movie_last_bytes, **movie_stage_tracker.to_dict()})

    movie_stage_tracker.on_update(_movie_emit_stage)
    # Emit initial state so T/L/E bars appear from the start
    _movie_emit_stage()

    def on_movie_bytes(downloaded_bytes: int, total_bytes: int) -> None:
        nonlocal movie_last_bytes, movie_last_downloaded, movie_last_total
        nonlocal movie_last_progress_bytes, movie_last_progress_at, movie_rate_bps
        now = time.monotonic()
        if movie_last_progress_bytes is None or downloaded_bytes < movie_last_progress_bytes:
            movie_rate_bps = 0.0
        else:
            elapsed = max(0.001, now - (movie_last_progress_at or now))
            delta = downloaded_bytes - movie_last_progress_bytes
            movie_rate_bps = delta / elapsed if delta else 0.0
        movie_last_progress_bytes = downloaded_bytes
        movie_last_progress_at = now
        movie_last_downloaded = downloaded_bytes
        movie_last_total = total_bytes
        movie_last_bytes = {
            "type": "bytes",
            "title": title,
            "season": None,
            "episode": None,
            "current": 1,
            "total": 1,
            "downloaded": downloaded_bytes,
            "bytes_total": total_bytes,
            "rate_bps": movie_rate_bps,
            **movie_stage_tracker.to_dict(),
        }
        if progress_callback:
            with movie_progress_lock:
                progress_callback(movie_last_bytes)

    result: dict[str, Any] = {}
    error: BaseException | None = None
    try:
        raise_if_shutdown_requested()
        result = search_and_download(
            title=title,
            imdb_id=config.imdb_id,
            season=None,
            episode=None,
            folder_path=str(folder_path),
            preferred_quality=quality,
            preferred_languages=preferred_languages,
            working_addons=servers,
            content_type="movie",
            progress_callback=on_movie_bytes,
            bandwidth_limiter=bandwidth_limiter,
            experimental_addons=experimental_addons,
            stage_tracker=movie_stage_tracker,
            quality_fallbacks=config.quality.fallbacks if config.quality else None,
            allow_higher=config.quality.allow_higher if config.quality else False,
            allow_lower=config.quality.allow_lower if config.quality else True,
        )
    except BaseException as exc:
        error = exc
        raise
    finally:
        cancelled = isinstance(error, (DownloadCancelled, KeyboardInterrupt)) or shutdown_requested()
        if progress_callback:
            with movie_progress_lock:
                progress_callback({
                    "type": "episode_done",
                    "title": title,
                    "season": None,
                    "episode": None,
                    "current": 1,
                    "total": 1,
                    "success": bool(result.get("success")),
                    "outcome": "cancelled" if cancelled else ("downloaded" if result.get("success") else "failed"),
                    "reason": "interrupted" if cancelled else (str(error) if error else result.get("error")),
                    "downloaded": movie_last_downloaded,
                    "bytes_total": movie_last_total,
                    "rate_bps": 0.0,
                })

    if result.get("success"):
        successful_urls = _verified_urls_from_result(result)
        _save_verified_server_urls(config, config_path, successful_urls)
        filename = Path(result.get("filename", f"{title}.mkv")).name
        server = result.get("successful_url") or ""
        state.add_download(filename, result.get("quality", quality), "stremio", server=server)
        save_state(folder_path, state)
        return {"downloaded": 1, "skipped": 0}

    print(f"    No working streams found for movie: {title}")
    return {"downloaded": 0, "skipped": 0, "failed": 1, "error": result.get("error", "No streams resolved")}
