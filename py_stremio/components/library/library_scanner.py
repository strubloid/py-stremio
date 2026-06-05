"""Folder scanner for finding and categorizing content."""
from dataclasses import dataclass
from pathlib import Path
from enum import Enum

from py_stremio.components.configs.app_settings import settings


class FolderType(Enum):
    SERIES = "series"
    MOVIES = "movies"
    UNKNOWN = "unknown"


@dataclass
class ScannedFolder:
    path: Path
    folder_type: FolderType
    parent_folder: Path
    season_number: int | None = None


class Scanner:
    def __init__(self):
        self.root = settings.ROOT_FOLDER
        self.series_root = settings.SERIES_FOLDER
        self.movies_root = settings.MOVIES_FOLDER

    def ensure_folders(self):
        """Create root, series, and movies folders if missing."""
        self.series_root.mkdir(parents=True, exist_ok=True)
        self.movies_root.mkdir(parents=True, exist_ok=True)

    def scan(self) -> list[ScannedFolder]:
        """Scan all supported folders recursively."""
        folders = []
        for season_path in self._find_series_folders():
            folder = self._create_series_folder(season_path)
            if folder:
                folders.append(folder)
        for movie_path in self._find_movie_folders():
            folders.append(self._create_movie_folder(movie_path))
        return folders

    def _find_series_folders(self) -> list[Path]:
        """Find all series season folders."""
        folders = []
        if not self.series_root.exists():
            return folders
        for series_path in self.series_root.iterdir():
            if series_path.is_dir():
                pattern = "s*"
                for season_path in series_path.glob(pattern):
                    if season_path.is_dir():
                        folders.append(season_path)
        return folders

    def _find_movie_folders(self) -> list[Path]:
        """Find all movie group folders."""
        folders = []
        if not self.movies_root.exists():
            return folders
        for movie_path in self.movies_root.iterdir():
            if movie_path.is_dir():
                folders.append(movie_path)
        return folders

    def _create_series_folder(self, path: Path) -> ScannedFolder | None:
        """Create series folder record from path."""
        import re
        season_match = re.search(r"^s(\d+)$", path.name, re.IGNORECASE)
        if not season_match:
            return None
        season_number = int(season_match.group(1))
        return ScannedFolder(
            path=path,
            folder_type=FolderType.SERIES,
            parent_folder=path.parent,
            season_number=season_number,
        )

    def _create_movie_folder(self, path: Path) -> ScannedFolder:
        """Create movie folder record from path."""
        return ScannedFolder(
            path=path,
            folder_type=FolderType.MOVIES,
            parent_folder=path.parent,
        )