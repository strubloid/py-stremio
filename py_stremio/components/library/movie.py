"""Movie group management and download planning."""
from pathlib import Path

from py_stremio.components.configs.config_file import DownloadConfig, QualitySettings, load_config
from py_stremio.components.download.downloader import Downloader, plan_quality_fallback
from py_stremio.components.library.media_file import detect_movie_titles
from py_stremio.components.state.app_state import load_state, save_state
from py_stremio.components.configs.app_settings import settings


def detect_existing_movies(folder_path: Path) -> set[str]:
    """Detect existing movies in folder by scanning for video files."""
    return detect_movie_titles(folder_path)


def process_movies(folder_path: Path) -> dict:
    """Process a movie folder."""
    config, _ = load_config(folder_path)
    if not config.enabled:
        return {"skipped": True, "reason": "disabled"}

    state = load_state(folder_path)
    existing_movies = detect_existing_movies(folder_path)
    downloader = Downloader(folder_path, config)
    results = {"downloaded": [], "failed": [], "skipped": 0, "dry_run": settings.DRY_RUN}

    movie_title = config.search_group or config.title or folder_path.name.replace("-", " ").replace("_", " ").title()
    quality = config.quality or QualitySettings()
    target_quality = quality.preferred
    qualities = plan_quality_fallback(quality, target_quality)
    movie_filename = f"{movie_title}_[{target_quality}].mkv"

    if state.is_downloaded(movie_filename):
        results["skipped"] = 1
    else:
        result = downloader.download_with_fallback(movie_filename, qualities)
        if result.success:
            state.add_download(movie_filename, result.quality or target_quality, result.provider)
            results["downloaded"].append({"quality": result.quality})
            print(f"    Downloaded: {movie_title} ({result.quality})")
        else:
            results["failed"].append({"error": result.error})
            print(f"    Failed: {movie_title} - {result.error}")

    save_state(folder_path, state)
    return results
