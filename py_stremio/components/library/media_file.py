"""Reusable media file discovery helpers."""
from dataclasses import dataclass
from pathlib import Path

from py_stremio.utils.media import parse_episode_number


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


def detect_existing_season_episodes(folder_path: Path, episode_count: int | None) -> set[int]:
    """Infer completed season-local episode numbers from files in a season folder.

    Some release groups name later seasons with absolute/anime episode numbers
    (for example season 3 files numbered 27-40). When the folder contains a
    consecutive block outside the season-local 1..N range, treat the first file
    as season episode 1, the second as episode 2, and so on. If filenames do not
    expose any episode numbers, fall back to counting video files only when the
    season episode count is known.
    """
    files = scan_episode_files(folder_path)
    if not files:
        return set()

    if not episode_count or episode_count <= 0:
        return {media_file.episode for media_file in files if media_file.episode is not None}

    parsed = sorted(media_file.episode for media_file in files if media_file.episode is not None)
    season_local = {episode for episode in parsed if 1 <= episode <= episode_count}
    if season_local:
        return season_local

    if parsed:
        is_consecutive = parsed == list(range(parsed[0], parsed[0] + len(parsed)))
        if is_consecutive:
            return set(range(1, min(len(parsed), episode_count) + 1))
        return set()

    return set(range(1, min(len(files), episode_count) + 1))


def infer_next_episode_download(folder_path: Path, episode_count: int | None) -> int | None:
    """Return the first missing season-local episode after scanning existing files."""
    if not episode_count or episode_count <= 0:
        return None
    existing = detect_existing_season_episodes(folder_path, episode_count)
    for episode in range(1, episode_count + 1):
        if episode not in existing:
            return episode
    return episode_count + 1


def detect_movie_titles(folder_path: Path) -> set[str]:
    """Detect movie titles from supported video file names."""
    return {file_path.stem for file_path in iter_video_files(folder_path)}
