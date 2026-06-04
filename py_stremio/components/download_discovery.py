"""Discover folders that can be processed by the download manager."""
from pathlib import Path


CONFIG_FILENAME = "download-config.json"
STATE_FILENAME = ".download-state.json"


def has_download_metadata(folder_path: Path) -> bool:
    """Return True when a folder has config or state metadata."""
    return (folder_path / STATE_FILENAME).exists() or (folder_path / CONFIG_FILENAME).exists()


def find_season_folders(root_folder: Path) -> list[Path]:
    """Find all season folders with state/config files."""
    season_folders = []
    series_root = root_folder / "series"
    if not series_root.exists():
        return season_folders

    for show_folder in series_root.iterdir():
        if not show_folder.is_dir():
            continue
        for season_folder in show_folder.iterdir():
            if season_folder.is_dir() and has_download_metadata(season_folder):
                season_folders.append(season_folder)
    return season_folders


def find_movie_folders(root_folder: Path) -> list[Path]:
    """Find all movie folders with state/config files."""
    movie_folders = []
    movies_root = root_folder / "movies"
    if not movies_root.exists():
        return movie_folders

    for group_folder in movies_root.iterdir():
        if group_folder.is_dir() and has_download_metadata(group_folder):
            movie_folders.append(group_folder)
    return movie_folders
