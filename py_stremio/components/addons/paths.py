"""Canonical paths for external addon inventory files."""
from pathlib import Path


ADDONS_DIRECTORY = "addons"
CUSTOM_ADDONS_FILE = "addons.txt"
STREMIO_ADDONS_FILE = "stremio.txt"
EXPERIMENTAL_ADDONS_FILE = "experimental.txt"


def find_project_root() -> Path:
    """Return the nearest project root, falling back to the current directory."""
    start = Path.cwd()
    for path in (start, *start.parents):
        if (path / "pyproject.toml").exists():
            return path
    return start


def addons_directory() -> Path:
    return find_project_root() / ADDONS_DIRECTORY


def custom_addons_path() -> Path:
    return addons_directory() / CUSTOM_ADDONS_FILE


def stremio_addons_path() -> Path:
    return addons_directory() / STREMIO_ADDONS_FILE


def experimental_addons_path() -> Path:
    return addons_directory() / EXPERIMENTAL_ADDONS_FILE
