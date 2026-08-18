"""Canonical paths for external addon inventory files."""
import os
from pathlib import Path


ADDONS_DIRECTORY = "addons"
CUSTOM_ADDONS_FILE = "addons.txt"
STREMIO_ADDONS_FILE = "stremio.txt"
EXPERIMENTAL_ADDONS_FILE = "experimental.txt"


def find_project_root() -> Path:
    """Return the nearest project root, falling back to the current directory.

    Respects ``PY_STREMIO_PROJECT_ROOT`` env var (set by cron wrapper) to point
    to the actual project directory. Falls back to walking up from cwd if not set.
    """
    if os.getenv("PY_STREMIO_PROJECT_ROOT"):
        root = Path(os.environ["PY_STREMIO_PROJECT_ROOT"])
        if (root / "pyproject.toml").exists():
            return root
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
