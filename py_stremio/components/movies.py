"""Movie group management and download planning."""
from pathlib import Path

from .config_file import DownloadConfig, load_config
from .downloader import Downloader, plan_quality_fallback
from .media_files import detect_movie_titles
from .state import load_state, save_state
from .settings import settings


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

    movie_title = config.search_group
    target_quality = config.quality.preferred
    qualities = plan_quality_fallback(config.quality, target_quality)
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
