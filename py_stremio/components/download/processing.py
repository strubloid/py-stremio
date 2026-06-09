"""Process configured series and movie folders."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading
import time

from py_stremio.components.configs.config_file import load_config, save_config
from py_stremio.components.library.media_file import detect_existing_season_episodes, iter_video_files, scan_episode_files
from py_stremio.components.reports.output_writer import suppress_current_thread_output
from py_stremio.components.configs.app_settings import settings
from py_stremio.components.state.app_state import load_state, save_state
from py_stremio.components.stremio.stremio_client import search_and_download
from py_stremio.utils.cancellation import request_shutdown, shutdown_executor_now, shutdown_requested
from py_stremio.components.download.stream_download import build_media_filename
from py_stremio.components.stremio.stremio_url import normalize_manifest_url, unique_manifest_urls
from py_stremio.components.addons.addon_search_service import preflight_discover_working_addons
from py_stremio.components.stremio.stremio_ids import build_stremio_id


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
        if not record.server and not record.addon_url:  # server not recorded
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
    print(f"    Disabled {len(combined)} server(s) that previously delivered wrong content")
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
    missing = []
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


def process_season_folder(
    folder_path: Path,
    progress_callback=None,
    max_workers: int = 1,
    bandwidth_limiter=None,
    worker_semaphore: threading.Semaphore | None = None,
    quiet_output: bool = False,
) -> dict:
    """Process a season folder and download missing episodes from Stremio."""
    config, config_path = load_config(folder_path)
    state = load_state(folder_path)

    if not config.enabled:
        return {"skipped": True, "reason": "disabled"}

    # ── Disabled-server cleanup ────────────────────────────────────────
    # Scan all state entries for files that were downloaded but are now
    # missing (user deleted = wrong content). Disable those servers so they
    # are never queried again for this folder.
    _update_disabled_servers(state, config, config_path, folder_path)

    if not config.title:
        return {"skipped": True, "reason": "no title in config"}
    title = config.title

    season = config.season if config.season is not None else 1
    if config.episode_count is None:
        return {"skipped": True, "reason": "season metadata has no episodes"}

    quality = _preferred_quality(config)
    preferred_languages = _preferred_languages(config)
    final_episode = config.episode_count
    episodes = scan_folder_for_episodes(folder_path)
    existing_episodes = detect_existing_season_episodes(folder_path, config.episode_count)
    start_episode = max(1, config.current_episode_download or 1)
    missing = _missing_episodes(folder_path, config, state, season, existing_episodes)

    if missing:
        _set_current_episode(config, config_path, missing[0])
    elif start_episode <= final_episode and config.available_episodes is None:
        _set_current_episode(config, config_path, final_episode + 1)

    # ── Pre-flight addon discovery ──────────────────────────────────────────
    # If the server cache is empty, scan ALL addons once using the first
    # missing episode to discover which addons actually have content for this
    # show.  Subsequent episode downloads will only query these confirmed
    # working addons instead of the full ~65-addon list every time.
    servers = unique_manifest_urls(config.servers)
    disabled = set(unique_manifest_urls(config.disabled_servers))
    if disabled:
        filtered = [s for s in servers if s not in disabled]
        if len(filtered) < len(servers):
            print(f"    Excluded {len(servers) - len(filtered)} disabled server(s) that delivered wrong content")
            servers = filtered
    if missing and not servers and config.imdb_id:
        print(f"\n  {'='*50}")
        print(f"  Pre-flight: discovering working addons for {title}")
        print(f"  {'='*50}")
        first_episode = missing[0]
        stremio_id = build_stremio_id(config.imdb_id, title, season, first_episode)
        discovered = preflight_discover_working_addons("series", stremio_id)
        if discovered:
            servers = discovered
            _save_verified_server_urls(config, config_path, servers)
            print(f"  Using {len(discovered)} pre-confirmed addons for this season\n")
        else:
            print(f"  Pre-flight found no working addons — will search all per-episode\n")
    elif not servers and missing:
        print(f"  No server cache and no IMDB ID — will search all addons per-episode\n")

    downloaded = 0
    skipped = 0
    failed = 0
    verified_servers: list[str] = []
    servers_lock = threading.Lock()
    config_lock = threading.Lock()
    progress_lock = threading.Lock()
    total_missing = len(missing)

    def emit(event: dict) -> None:
        if progress_callback:
            with progress_lock:
                progress_callback(event)

    def download_episode(index: int, episode_num: int) -> dict:
        last_downloaded_bytes = 0
        last_total_bytes = 0
        last_rate_bps = 0.0
        last_progress_bytes = 0
        last_progress_at = time.monotonic()
        emit({
            "type": "episode_start",
            "title": title,
            "season": season,
            "episode": episode_num,
            "current": index,
            "total": total_missing,
        })

        def on_bytes(downloaded_bytes: int, total_bytes: int) -> None:
            nonlocal last_downloaded_bytes, last_total_bytes, last_rate_bps, last_progress_bytes, last_progress_at
            now = time.monotonic()
            elapsed = max(0.001, now - last_progress_at)
            delta = max(0, downloaded_bytes - last_progress_bytes)
            if delta:
                last_rate_bps = delta / elapsed
                last_progress_bytes = downloaded_bytes
                last_progress_at = now
            last_downloaded_bytes = downloaded_bytes
            last_total_bytes = total_bytes
            emit({
                "type": "bytes",
                "title": title,
                "season": season,
                "episode": episode_num,
                "current": index,
                "total": total_missing,
                "downloaded": downloaded_bytes,
                "bytes_total": total_bytes,
                "rate_bps": last_rate_bps,
            })

        print(f"  Downloading {title} S{season:02d}E{episode_num:02d}")
        # If this episode was previously downloaded but the file is missing
        # (user deleted it = wrong content), exclude the server that provided it
        generated_filename = _generated_episode_filename(folder_path, config, season, episode_num)
        legacy_key = f"episode_{episode_num}.mkv"
        bad_servers: list[str] = []
        for state_key in (generated_filename, legacy_key):
            if state.is_downloaded(state_key):
                previous_url = state.get_server(state_key)
                if previous_url:
                    bad_servers.append(previous_url)
        # Persist bad servers to disabled_servers so they never get re-queried
        if bad_servers:
            with config_lock:
                new_disabled = unique_manifest_urls(bad_servers + config.disabled_servers)
                if new_disabled != unique_manifest_urls(config.disabled_servers):
                    config.disabled_servers = new_disabled
                    save_config(config_path, config)
        with servers_lock:
            active_servers = [s for s in servers if s not in bad_servers]
        if bad_servers:
            print(f"    ⚠ Previous server(s) delivered wrong content — excluded from retry")
        result = search_and_download(
            title=title,
            imdb_id=config.imdb_id,
            season=season,
            episode=episode_num,
            folder_path=str(folder_path),
            preferred_quality=quality,
            preferred_languages=preferred_languages,
            working_addons=active_servers,
            progress_callback=on_bytes,
            bandwidth_limiter=bandwidth_limiter,
        )
        emit({
            "type": "episode_done",
            "title": title,
            "season": season,
            "episode": episode_num,
            "current": index,
            "total": total_missing,
            "success": bool(result.get("success")),
            "downloaded": last_downloaded_bytes,
            "bytes_total": last_total_bytes,
            "rate_bps": last_rate_bps,
        })
        return {"episode": episode_num, "result": result}

    def _download_episode_with_slot(index: int, episode_num: int) -> dict:
        if worker_semaphore:
            worker_semaphore.acquire()
        try:
            if quiet_output:
                with suppress_current_thread_output():
                    return download_episode(index, episode_num)
            return download_episode(index, episode_num)
        finally:
            if worker_semaphore:
                worker_semaphore.release()

    def apply_result(episode_num: int, result: dict, completed_successes: set[int] | None = None) -> None:
        nonlocal downloaded, failed, servers, verified_servers
        if result.get("success"):
            filename = Path(result.get("filename", f"episode_{episode_num}.mkv")).name
            server = result.get("successful_url") or ""
            state.add_download(filename, result.get("quality", quality), "stremio", server=server)
            save_state(folder_path, state)  # persist immediately after each download
            downloaded += 1
            successful_urls = _verified_urls_from_result(result)
            for successful_url in successful_urls:
                if successful_url and successful_url not in verified_servers:
                    verified_servers.append(successful_url)
                    print(f"    ✓ Verified download server: {successful_url}")
            with servers_lock:
                servers = _save_verified_server_urls(config, config_path, verified_servers)
            if completed_successes is not None:
                completed_successes.add(episode_num)
                next_cursor = min((ep for ep in missing if ep not in completed_successes), default=max(missing) + 1)
                _set_current_episode(config, config_path, next_cursor)
            else:
                _set_current_episode(config, config_path, episode_num + 1)
        else:
            state.mark_failed(f"episode_{episode_num}", result.get("error", "failed"), 1)
            failed += 1

    max_attempts = getattr(settings, "MAX_DOWNLOAD_ATTEMPTS", 5)
    queue = deque(missing)
    completed_successes: set[int] = set()

    if max_workers > 1 and total_missing > 1:
        # Parallel with retry rounds — try failed episodes again in subsequent rounds
        for round_num in range(max_attempts):
            if shutdown_requested() or not queue:
                break
            round_items = list(queue)
            queue.clear()
            print(f"  Round {round_num + 1}: {len(round_items)} episodes")
            executor = ThreadPoolExecutor(max_workers=max(1, max_workers))
            futures = []
            try:
                futures = [
                    executor.submit(_download_episode_with_slot, idx, ep_num)
                    for idx, ep_num in enumerate(round_items, start=1)
                ]
                future_map = {future: ep_num for future, ep_num in zip(futures, round_items)}
                for future in as_completed(future_map):
                    if shutdown_requested():
                        break
                    item = future.result()
                    if item["result"].get("success"):
                        apply_result(item["episode"], item["result"], completed_successes)
                    elif item["result"].get("permanent_failure"):
                        apply_result(item["episode"], item["result"])
                    else:
                        queue.append(item["episode"])
            except KeyboardInterrupt:
                request_shutdown()
                shutdown_executor_now(executor, futures)
                raise
            else:
                executor.shutdown(wait=True)
            if queue:
                print(f"  -> {len(queue)} episodes deferred to next round")
    else:
        # Sequential with retry rounds
        for round_num in range(max_attempts):
            if shutdown_requested() or not queue:
                break
            round_items = list(queue)
            queue.clear()
            if round_num > 0:
                print(f"  Round {round_num + 1}: retrying {len(round_items)} deferred episodes")
            for index, episode_num in enumerate(round_items, start=1):
                _set_current_episode(config, config_path, episode_num)
                item = download_episode(index, episode_num)
                if item["result"].get("success"):
                    apply_result(item["episode"], item["result"])
                elif item["result"].get("permanent_failure"):
                    apply_result(item["episode"], item["result"])
                else:
                    queue.append(episode_num)
            if queue:
                print(f"  -> {len(queue)} episodes deferred to next round")

    # Mark episodes that exhausted all rounds as permanently failed
    for episode_num in queue:
        state.mark_failed(f"episode_{episode_num}", "All retry rounds exhausted", max_attempts)
        failed += 1

    if missing:
        with servers_lock:
            servers = _save_verified_server_urls(config, config_path, verified_servers)

    for ep in episodes:
        if ep["path"].exists() and not state.is_downloaded(ep["filename"]):
            state.add_download(ep["filename"], quality, "stremio")
            skipped += 1

    save_state(folder_path, state)
    return {"downloaded": downloaded, "skipped": skipped, "failed": failed}


def process_movie_folder(folder_path: Path, progress_callback=None, bandwidth_limiter=None) -> dict:
    """Process a movie folder and download missing content from Stremio."""
    config, config_path = load_config(folder_path)
    state = load_state(folder_path)

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

    title = config.search_group or config.title or folder_path.name
    servers = unique_manifest_urls(config.servers)
    disabled = set(unique_manifest_urls(config.disabled_servers))
    if disabled:
        filtered = [s for s in servers if s not in disabled]
        if len(filtered) < len(servers):
            print(f"    Excluded {len(servers) - len(filtered)} disabled server(s) that delivered wrong content")
            servers = filtered
    preferred_languages = _preferred_languages(config)

    # Pre-flight addon discovery for movies
    # Always run pre-flight to find which addons serve this title.
    # Use IMDB ID if available, otherwise title-based search ID.
    stremio_id = build_stremio_id(config.imdb_id, title, None, None) if config.imdb_id else build_stremio_id(None, title, None, None)
    if not servers:
        print(f"\n  {'='*50}")
        print(f"  Pre-flight: discovering working addons for movie '{title}'")
        print(f"  {'='*50}")
        discovered = preflight_discover_working_addons("movie", stremio_id)
        if discovered:
            servers = discovered
            _save_verified_server_urls(config, config_path, servers)
            print(f"  Using {len(discovered)} pre-confirmed addons for this movie\n")
        else:
            print(f"  Pre-flight found no working addons — will search all\n")
    else:
        print(f"  Using {len(servers)} cached server(s)\n")

    print(f"  Searching for movie: {title}")
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
        progress_callback=lambda downloaded, total: progress_callback({
            "type": "bytes",
            "title": title,
            "season": None,
            "episode": None,
            "current": 1,
            "total": 1,
            "downloaded": downloaded,
            "bytes_total": total,
        }) if progress_callback else None,
        bandwidth_limiter=bandwidth_limiter,
    )

    if result.get("success"):
        successful_urls = _verified_urls_from_result(result)
        _save_verified_server_urls(config, config_path, successful_urls)
        filename = Path(result.get("filename", f"{title}.mkv")).name
        server = result.get("successful_url") or ""
        state.add_download(filename, result.get("quality", quality), "stremio", server=server)
        save_state(folder_path, state)
        return {"downloaded": 1, "skipped": 0}

    _save_verified_server_urls(config, config_path, [])
    return {"downloaded": 0, "skipped": 0, "failed": 1, "error": result.get("error")}
