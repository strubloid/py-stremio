"""CLI orchestration for config/state driven downloads."""
from pathlib import Path
import sys

from .download_discovery import find_movie_folders, find_season_folders
from .download_processing import process_movie_folder, process_season_folder, scan_folder_for_episodes
from .settings import settings
from .stremio_urls import normalize_manifest_url, unique_manifest_urls


normalize_server_url = normalize_manifest_url
unique_server_urls = unique_manifest_urls


def run_downloads(root_folder: Path | None = None) -> dict:
    """Run all downloads based on state and config files."""
    if root_folder is None:
        root_folder = Path(settings.ROOT_FOLDER)

    results = {
        "series": [],
        "movies": [],
        "total_downloaded": 0,
        "total_skipped": 0,
        "total_failed": 0,
    }

    season_folders = find_season_folders(root_folder)
    for folder in season_folders:
        print(f"Processing series: {folder.name}")
        result = process_season_folder(folder)
        results["series"].append({"folder": str(folder), **result})
        results["total_downloaded"] += result.get("downloaded", 0)
        results["total_skipped"] += result.get("skipped", 0)
        results["total_failed"] += result.get("failed", 0)

    movie_folders = find_movie_folders(root_folder)
    for folder in movie_folders:
        print(f"Processing movies: {folder.name}")
        result = process_movie_folder(folder)
        results["movies"].append({"folder": str(folder), **result})
        results["total_downloaded"] += result.get("downloaded", 0)
        results["total_skipped"] += result.get("skipped", 0)
        results["total_failed"] += result.get("failed", 0)

    return results


def main():
    """CLI entry point."""
    root = sys.argv[1] if len(sys.argv) > 1 else settings.ROOT_FOLDER
    root_path = Path(root)

    if not root_path.exists():
        print(f"Error: Root folder does not exist: {root}")
        sys.exit(1)

    print(f"Starting downloads from: {root_path}")
    results = run_downloads(root_path)

    print("\n=== Download Summary ===")
    print(f"Total Downloaded: {results['total_downloaded']}")
    print(f"Total Skipped: {results['total_skipped']}")
    print(f"Total Failed: {results['total_failed']}")


if __name__ == "__main__":
    main()
