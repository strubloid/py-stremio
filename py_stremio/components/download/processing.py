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
from py_stremio.components.download.stream_download import build_media_filename
from py_stremio.components.stremio.stremio_url import normalize_manifest_url, unique_manifest_urls


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
    config.current_episode_download = max(1, episode)
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

    if not config.title:
        return {"skipped": True, "reason": "no title in config"}

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

    downloaded = 0
    skipped = 0
    failed = 0
    servers = unique_manifest_urls(config.servers)
    verified_servers: list[str] = []
    servers_lock = threading.Lock()
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
            "title": config.title,
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
                "title": config.title,
                "season": season,
                "episode": episode_num,
                "current": index,
                "total": total_missing,
                "downloaded": downloaded_bytes,
                "bytes_total": total_bytes,
                "rate_bps": last_rate_bps,
            })

        print(f"  Downloading {config.title} S{season:02d}E{episode_num:02d}")
        with servers_lock:
            active_servers = list(servers)
        result = search_and_download(
            title=config.title,
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
            "title": config.title,
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
            state.add_download(filename, result.get("quality", quality), "stremio")
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
            if not queue:
                break
            round_items = list(queue)
            queue.clear()
            print(f"  Round {round_num + 1}: {len(round_items)} episodes")
            with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
                futures = {
                    executor.submit(_download_episode_with_slot, idx, ep_num): ep_num
                    for idx, ep_num in enumerate(round_items, start=1)
                }
                for future in as_completed(futures):
                    item = future.result()
                    if item["result"].get("success"):
                        apply_result(item["episode"], item["result"], completed_successes)
                    elif item["result"].get("permanent_failure"):
                        apply_result(item["episode"], item["result"])
                    else:
                        queue.append(item["episode"])
            if queue:
                print(f"  -> {len(queue)} episodes deferred to next round")
    else:
        # Sequential with retry rounds
        for round_num in range(max_attempts):
            if not queue:
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
    preferred_languages = _preferred_languages(config)

    print(f"  Searching for movie: {title}")
    result = search_and_download(
        title=title,
        season=None,
        episode=None,
        folder_path=str(folder_path),
        preferred_quality=quality,
        preferred_languages=preferred_languages,
        working_addons=servers,
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
        state.add_download(filename, result.get("quality", quality), "stremio")
        save_state(folder_path, state)
        return {"downloaded": 1, "skipped": 0}

    _save_verified_server_urls(config, config_path, [])
    return {"downloaded": 0, "skipped": 0, "failed": 1, "error": result.get("error")}
