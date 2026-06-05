"""Series episode management and download planning."""
from pathlib import Path

from py_stremio.components.configs.config_file import DownloadConfig, QualitySettings, load_config
from py_stremio.components.download.downloader import Downloader, plan_quality_fallback
from py_stremio.components.library.media_file import detect_episode_numbers
from py_stremio.components.state.app_state import load_state, save_state
from py_stremio.utils.media import sanitize_filename
from py_stremio.components.configs.app_settings import settings


def detect_existing_episodes(folder_path: Path) -> set[int]:
    """Detect existing episodes in folder by scanning for video files."""
    return detect_episode_numbers(folder_path)


def plan_missing_episodes(config: DownloadConfig, existing_episodes: set[int]) -> list[int]:
    """Plan which episodes need to be downloaded."""
    if config.episode_count is None:
        return []
    all_episodes = set(range(1, config.episode_count + 1))
    return sorted(all_episodes - existing_episodes)


def process_series(folder_path: Path) -> dict:
    """Process a series folder for missing episodes."""
    config, _ = load_config(folder_path)
    if not config.enabled:
        return {"skipped": True, "reason": "disabled"}

    state = load_state(folder_path)
    existing_episodes = detect_existing_episodes(folder_path)
    missing_episodes = plan_missing_episodes(config, existing_episodes)

    downloader = Downloader(folder_path, config)
    results = {"downloaded": [], "failed": [], "skipped": 0, "dry_run": settings.DRY_RUN}

    for ep_num in missing_episodes:
        episode_key = f"episode_{ep_num:02d}.mkv"
        if state.is_downloaded(episode_key):
            results["skipped"] += 1
            continue
        quality = config.quality or QualitySettings()
        target_quality = quality.preferred
        qualities = plan_quality_fallback(quality, target_quality)
        series_title = config.title or folder_path.parent.name.replace("-", " ").replace("_", " ").title()
        season = config.season or 1
        episode_title = f"{series_title} S{season:02d}E{ep_num:02d}"
        result = downloader.download_with_fallback(
            f"{sanitize_filename(series_title)}_S{season:02d}E{ep_num:02d}_[{target_quality}].mkv",
            qualities
        )
        if result.success:
            state.add_download(episode_key, result.quality or target_quality, result.provider)
            results["downloaded"].append({"episode": ep_num, "quality": result.quality})
            print(f"    Downloaded: {episode_title} ({result.quality})")
        else:
            results["failed"].append({"episode": ep_num, "error": result.error})
            print(f"    Failed: {episode_title} - {result.error}")

    save_state(folder_path, state)
    return results
