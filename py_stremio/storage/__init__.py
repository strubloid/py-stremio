"""Storage layer - SQLite catalog for config, state, and inventory."""
from .db import get_connection, close_connection, init_db, transaction, execute, fetchone, fetchall, get_db_path
from .catalog import (
    get_missing_episodes,
    get_stale_seasons,
    get_stale_movies,
    get_folders_needing_inventory_sync,
    get_folders_needing_metadata_refresh,
    get_series_needing_new_season_check,
    upsert_addon,
    get_addon_status,
    record_job_run,
    get_recent_job_runs,
    set_runtime_setting,
    get_runtime_setting,
    MissingEpisode,
    StaleFolder,
)
from .migration import migrate, export_json

# Repositories are not imported at package level to avoid circular imports
# Import them directly: from py_stremio.storage.repositories import SeasonRepo, MovieRepo, AddonRepo

__all__ = [
    # db
    "get_connection",
    "close_connection",
    "init_db",
    "transaction",
    "execute",
    "fetchone",
    "fetchall",
    "get_db_path",
    # catalog
    "get_missing_episodes",
    "get_stale_seasons",
    "get_stale_movies",
    "get_folders_needing_inventory_sync",
    "get_folders_needing_metadata_refresh",
    "get_series_needing_new_season_check",
    "upsert_addon",
    "get_addon_status",
    "record_job_run",
    "get_recent_job_runs",
    "set_runtime_setting",
    "get_runtime_setting",
    "MissingEpisode",
    "StaleFolder",
    # migration
    "migrate",
    "export_json",
]