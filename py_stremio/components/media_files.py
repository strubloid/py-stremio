"""Reusable media file discovery helpers."""
from dataclasses import dataclass
from pathlib import Path

from .utils import parse_episode_number


VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".m4v"}


@dataclass(frozen=True)
class MediaFile:
    path: Path
    episode: int | None = None

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def title(self) -> str:
        return self.path.stem


def is_video_file(file_path: Path) -> bool:
    """Return True when the path is a supported video file."""
    return file_path.is_file() and file_path.suffix.lower() in VIDEO_EXTENSIONS


def iter_video_files(folder_path: Path) -> list[Path]:
    """List supported video files in a folder."""
    if not folder_path.exists():
        return []
    return [file_path for file_path in folder_path.iterdir() if is_video_file(file_path)]


def scan_episode_files(folder_path: Path) -> list[MediaFile]:
    """List video files with parsed episode numbers."""
    episode_files = [
        MediaFile(path=file_path, episode=parse_episode_number(file_path.name))
        for file_path in iter_video_files(folder_path)
    ]
    return sorted(episode_files, key=lambda item: item.episode or 0)


def detect_episode_numbers(folder_path: Path) -> set[int]:
    """Detect episode numbers from supported video files."""
    return {
        media_file.episode
        for media_file in scan_episode_files(folder_path)
        if media_file.episode is not None
    }


def detect_movie_titles(folder_path: Path) -> set[str]:
    """Detect movie titles from supported video file names."""
    return {file_path.stem for file_path in iter_video_files(folder_path)}
