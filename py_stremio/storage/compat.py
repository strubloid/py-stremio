"""Compatibility shims for load_config/load_state with STORAGE_BACKEND switch."""
from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from typing import Any, TYPE_CHECKING

from py_stremio.components.configs.app_settings import settings

if TYPE_CHECKING:
    from py_stremio.components.configs.config_file import DownloadConfig
    from py_stremio.components.state.app_state import DownloadState


# Backend cache
_storage_backend: str | None = None


def get_storage_backend() -> str:
    """Get the active storage backend, caching the setting."""
    global _storage_backend
    if _storage_backend is None:
        configured = os.environ.get("STORAGE_BACKEND")
        if configured is None and getattr(settings, "STORAGE_BACKEND", "json") != "json":
            configured = settings.STORAGE_BACKEND
        if configured is not None:
            _storage_backend = configured.lower().strip()
        else:
            _storage_backend = "json"
            from py_stremio.storage.db import get_db_path

            db_path = get_db_path()
            if db_path.is_file():
                try:
                    connection = sqlite3.connect(str(db_path))
                    row = connection.execute(
                        "SELECT value FROM meta WHERE key = 'migration_complete'"
                    ).fetchone()
                    connection.close()
                    if row and row[0] == "1":
                        _storage_backend = "sqlite"
                except sqlite3.Error:
                    pass
        if _storage_backend not in ("json", "sqlite"):
            _storage_backend = "json"
    return _storage_backend


def use_sqlite() -> bool:
    """Check if SQLite backend is active."""
    return get_storage_backend() == "sqlite"


def load_config(folder_path: Path) -> "tuple[DownloadConfig, Path]":
    """Load config using active backend."""
    if use_sqlite():
        return _load_config_sqlite(folder_path)
    from py_stremio.components.configs.config_file import _load_config_json as load_json_config
    return load_json_config(folder_path)


def save_config(config_path: Path, config: "DownloadConfig") -> None:
    """Save config using active backend."""
    if use_sqlite():
        return _save_config_sqlite(config_path, config)
    from py_stremio.components.configs.config_file import _save_config_json as save_json_config
    save_json_config(config_path, config)


def load_state(folder_path: Path) -> "DownloadState":
    """Load state using active backend."""
    if use_sqlite():
        return _load_state_sqlite(folder_path)
    from py_stremio.components.state.app_state import _load_state_json as load_json_state
    return load_json_state(folder_path)


def save_state(folder_path: Path, state: "DownloadState") -> None:
    """Save state using active backend."""
    if use_sqlite():
        return _save_state_sqlite(folder_path, state)
    from py_stremio.components.state.app_state import _save_state_json as save_json_state
    save_json_state(folder_path, state)


def _load_config_sqlite(folder_path: Path) -> tuple[DownloadConfig, Path]:
    """Load config from SQLite via repository."""
    from py_stremio.storage.repositories import SeasonRepo, MovieRepo
    from py_stremio.components.configs.config_file import is_series_season_folder
    from py_stremio.components.configs.app_settings import settings

    if is_series_season_folder(folder_path):
        repo = SeasonRepo.from_folder(folder_path, settings.ROOT_FOLDER)
    else:
        repo = MovieRepo.from_folder(folder_path, settings.ROOT_FOLDER)
    return repo.config, folder_path / "download-config.json"


def _save_config_sqlite(config_path: Path, config: DownloadConfig) -> None:
    """Save config to SQLite via repository."""
    from py_stremio.storage.repositories import SeasonRepo, MovieRepo
    from py_stremio.components.configs.config_file import is_series_season_folder
    from py_stremio.components.configs.app_settings import settings

    folder_path = config_path.parent
    if is_series_season_folder(folder_path):
        repo = SeasonRepo.from_folder(folder_path, settings.ROOT_FOLDER)
    else:
        repo = MovieRepo.from_folder(folder_path, settings.ROOT_FOLDER)
    repo.config = config
    repo.save_config()


def _load_state_sqlite(folder_path: Path) -> DownloadState:
    """Load state from SQLite via repository."""
    from py_stremio.storage.repositories import SeasonRepo, MovieRepo
    from py_stremio.components.configs.config_file import is_series_season_folder
    from py_stremio.components.configs.app_settings import settings

    if is_series_season_folder(folder_path):
        repo = SeasonRepo.from_folder(folder_path, settings.ROOT_FOLDER)
    else:
        repo = MovieRepo.from_folder(folder_path, settings.ROOT_FOLDER)
    return repo.state


def _save_state_sqlite(folder_path: Path, state: DownloadState) -> None:
    """Save state to SQLite via repository."""
    from py_stremio.storage.repositories import SeasonRepo, MovieRepo
    from py_stremio.components.configs.config_file import is_series_season_folder
    from py_stremio.components.configs.app_settings import settings

    if is_series_season_folder(folder_path):
        repo = SeasonRepo.from_folder(folder_path, settings.ROOT_FOLDER)
    else:
        repo = MovieRepo.from_folder(folder_path, settings.ROOT_FOLDER)
    repo.state = state
    repo.save_state()


# For backward compat - allow importing the old names
__all__ = [
    "load_config",
    "save_config",
    "load_state",
    "save_state",
    "get_storage_backend",
    "use_sqlite",
]
