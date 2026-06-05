"""Utility functions."""
from pathlib import Path
import re


def sanitize_filename(name: str) -> str:
    """Remove or replace characters invalid in filenames."""
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name.strip()


def parse_episode_number(filename: str) -> int | None:
    """Extract episode number from common episode filename patterns."""
    patterns = [
        r"S\d+E(\d+)",
        r"episode[_\s-]*(\d+)",
        r"(?:^|\s)[-–—]\s*(\d{1,4})(?=\D|$)",
        r"(?<![A-Za-z0-9])E(\d{1,3})(?![A-Za-z0-9])",
    ]
    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def parse_season_from_folder(folder_name: str) -> int | None:
    """Extract season number from folder like 's03' or 'Season_2'."""
    match = re.search(r"(?:s|season[_\s-]*)(\d+)", folder_name, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def natural_sort_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    """Generate a type-safe natural sort key for filenames."""
    parts = re.split(r'(\d+)', path.name)
    return tuple((0, int(part)) if part.isdigit() else (1, part.lower()) for part in parts)