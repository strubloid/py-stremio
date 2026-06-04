"""Process configured series and movie folders."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading

from .config_file import load_config, save_config
from .media_files import iter_video_files, scan_episode_files
from .settings import settings
from .state import load_state, save_state
from .stremio_client import search_and_download
from .stream_downloads import build_media_filename
from .stremio_urls import normalize_manifest_url, unique_manifest_urls


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


def _remember_working_urls(config, config_path: Path, urls: list[str] | None) -> list[str]:
    servers = unique_manifest_urls(config.servers)
    changed = False

    for url in urls or []:
        normalized = normalize_manifest_url(url)
        if normalized and normalized not in servers:
            servers.append(normalized)
            changed = True
            print(f"    ✓ Found working server: {normalized}")

    if servers and (changed or servers != config.servers):
        config.servers = servers
        save_config(config_path, config)
        print(f"  Saved {len(servers)} working servers to config")

    return servers


def _preferred_quality(config) -> str:
    return config.quality.preferred if config.quality else "1080p"


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
    for episode in range(start_episode, final_episode + 1):
        generated_filename = _generated_episode_filename(folder_path, config, season, episode)
        if state.is_downloaded(f"episode_{episode}.mkv") or state.is_downloaded(generated_filename):
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


def process_season_folder(folder_path: Path, progress_callback=None, max_workers: int = 1, bandwidth_limiter=None) -> dict:
    """Process a season folder and download missing episodes from Stremio."""
    config, config_path = load_config(folder_path)
    state = load_state(folder_path)

    if not config.enabled:
        return {"skipped": True, "reason": "disabled"}

    if not config.title:
        return {"skipped": True, "reason": "no title in config"}

    season = config.season or 1
    quality = _preferred_quality(config)
    episodes = scan_folder_for_episodes(folder_path)
    existing_episodes = {ep["episode"] for ep in episodes if ep["episode"]}
    final_episode = config.episode_count or 20
    start_episode = max(1, config.current_episode_download or 1)
    missing = _missing_episodes(folder_path, config, state, season, existing_episodes)

    if missing:
        _set_current_episode(config, config_path, missing[0])
    elif start_episode <= final_episode:
        _set_current_episode(config, config_path, final_episode + 1)

    downloaded = 0
    skipped = 0
    failed = 0
    servers = unique_manifest_urls(config.servers)
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
        emit({
            "type": "episode_start",
            "title": config.title,
            "season": season,
            "episode": episode_num,
            "current": index,
            "total": total_missing,
        })

        def on_bytes(downloaded_bytes: int, total_bytes: int) -> None:
            nonlocal last_downloaded_bytes, last_total_bytes
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
        })
        return {"episode": episode_num, "result": result}

    def apply_result(episode_num: int, result: dict, completed_successes: set[int] | None = None) -> None:
        nonlocal downloaded, failed, servers
        if result.get("success"):
            filename = Path(result.get("filename", f"episode_{episode_num}.mkv")).name
            state.add_download(filename, result.get("quality", quality), "stremio")
            downloaded += 1
            if completed_successes is not None:
                completed_successes.add(episode_num)
                next_cursor = min((ep for ep in missing if ep not in completed_successes), default=max(missing) + 1)
                _set_current_episode(config, config_path, next_cursor)
            else:
                _set_current_episode(config, config_path, episode_num + 1)
        else:
            state.mark_failed(f"episode_{episode_num}", result.get("error", "failed"), 1)
            failed += 1
        with servers_lock:
            servers = _remember_working_urls(config, config_path, result.get("working_urls", []))

    if max_workers > 1 and total_missing > 1:
        completed_successes: set[int] = set()
        with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
            futures = [executor.submit(download_episode, index, episode_num) for index, episode_num in enumerate(missing, start=1)]
            for future in as_completed(futures):
                item = future.result()
                apply_result(item["episode"], item["result"], completed_successes)
    else:
        for index, episode_num in enumerate(missing, start=1):
            _set_current_episode(config, config_path, episode_num)
            item = download_episode(index, episode_num)
            apply_result(item["episode"], item["result"])

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

    print(f"  Searching for movie: {title}")
    result = search_and_download(
        title=title,
        season=None,
        episode=None,
        folder_path=str(folder_path),
        preferred_quality=quality,
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

    _remember_working_urls(config, config_path, result.get("working_urls", []))

    if result.get("success"):
        filename = Path(result.get("filename", f"{title}.mkv")).name
        state.add_download(filename, result.get("quality", quality), "stremio")
        save_state(folder_path, state)
        return {"downloaded": 1, "skipped": 0}

    return {"downloaded": 0, "skipped": 0, "failed": 1, "error": result.get("error")}
