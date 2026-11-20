"""Synchronize scanned media folders and their files into the dashboard catalog."""
from __future__ import annotations

from collections.abc import Callable

from py_stremio.components.configs.app_settings import settings
from py_stremio.components.configs.config_file import load_config
from py_stremio.components.library.library_scanner import FolderType, ScannedFolder
from py_stremio.components.library.media_file import iter_video_files, scan_episode_files
from py_stremio.storage.catalog import (
    get_movie_by_rel_path,
    get_or_create_movie,
    get_or_create_season,
    get_or_create_series,
    get_season_by_rel_path,
    update_movie_inventory_synced,
    update_season_inventory_synced,
    update_series_latest_season,
    upsert_files,
)
from py_stremio.storage.db import execute, fetchall, init_db, transaction


def _config_values(config) -> dict:
    return {
        "episode_count": config.episode_count,
        "available_episodes": config.available_episodes,
        "current_episode_download": config.current_episode_download,
        "enabled": config.enabled,
        "quality": {
            "preferred": config.quality.preferred,
            "fallbacks": config.quality.fallbacks,
            "allow_higher": config.quality.allow_higher,
            "allow_lower": config.quality.allow_lower,
        } if config.quality else None,
        "languages": config.languages,
        "subtitles": config.subtitles,
        "provider": config.provider,
        "search_group": config.search_group,
        "download_all_related": config.download_all_related,
        "servers": config.servers,
        "disabled_servers": config.disabled_servers,
        "working_addons": config.working_addons,
        "experimental_addons_enabled": config.experimental_addons_enabled,
        "metadata_last_checked": config.metadata_last_checked,
    }


def sync_catalog_from_folders(
    folders: list[ScannedFolder],
    progress_callback: Callable[[str], None] | None = None,
    force: bool = True,
    remove_missing: bool = True,
) -> None:
    """Make catalog folders and file inventory match the completed filesystem scan."""
    init_db()
    root = settings.ROOT_FOLDER
    initial_season_paths = {row["rel_path"] for row in fetchall("SELECT rel_path FROM seasons")}
    initial_movie_paths = {row["rel_path"] for row in fetchall("SELECT rel_path FROM movies")}
    live_seasons: set[str] = set()
    live_movies: set[str] = set()
    series_ids: set[int] = set()

    for folder in folders:
        rel_path = str(folder.path.relative_to(root))
        try:
            folder_mtime_ns = folder.path.stat().st_mtime_ns
        except OSError:
            continue
        if not force and folder.folder_type == FolderType.SERIES:
            existing = get_season_by_rel_path(rel_path)
            if existing and existing["sync_mtime_ns"] == folder_mtime_ns:
                live_seasons.add(rel_path)
                series_ids.add(existing["series_id"])
                continue
        if not force and folder.folder_type == FolderType.MOVIES:
            existing = get_movie_by_rel_path(rel_path)
            if existing and existing["sync_mtime_ns"] == folder_mtime_ns:
                live_movies.add(rel_path)
                continue
        config, _ = load_config(folder.path)
        config_data = _config_values(config)
        if folder.folder_type == FolderType.SERIES:
            series_rel_path = str(folder.path.parent.relative_to(root))
            series_title = config.title or folder.path.parent.name.replace("-", " ").replace("_", " ").title()
            series_id = get_or_create_series(series_title, series_rel_path, config.imdb_id)
            season = folder.season_number or config.season or 1
            season_id = get_or_create_season(series_id, season, rel_path, config_data)
            execute("UPDATE seasons SET rel_path=? WHERE id=?", (rel_path, season_id))
            files = []
            for media in scan_episode_files(folder.path):
                try:
                    stat = media.path.stat()
                except OSError:
                    continue
                files.append({
                    "rel_path": media.path.name,
                    "episode": media.episode,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "is_part": False,
                })
            upsert_files("season", season_id, files)
            update_season_inventory_synced(season_id, folder_mtime_ns)
            update_series_latest_season(series_id, season)
            live_seasons.add(rel_path)
            series_ids.add(series_id)
            label = f"{series_title} S{season:02d}"
            if rel_path not in initial_season_paths and progress_callback:
                progress_callback(f"Added to library: {label}")
        elif folder.folder_type == FolderType.MOVIES:
            title = config.title or folder.path.name
            movie_id = get_or_create_movie(title, rel_path, config.imdb_id, config_data)
            files = []
            for media in iter_video_files(folder.path):
                try:
                    stat = media.stat()
                except OSError:
                    continue
                files.append({
                    "rel_path": media.name,
                    "episode": None,
                    "size": stat.st_size,
                    "mtime_ns": stat.st_mtime_ns,
                    "is_part": False,
                })
            upsert_files("movie", movie_id, files)
            update_movie_inventory_synced(movie_id, folder_mtime_ns)
            live_movies.add(rel_path)
            label = title
            if rel_path not in initial_movie_paths and progress_callback:
                progress_callback(f"Added to library: {label}")
        else:
            continue

        if progress_callback:
            progress_callback(f"Catalog updated: {label} · {len(files)} file(s)")

    existing_folder_count = len(fetchall("SELECT id FROM seasons")) + len(fetchall("SELECT id FROM movies"))
    scanned_folder_count = len(live_seasons) + len(live_movies)
    if remove_missing and existing_folder_count and (
        scanned_folder_count == 0
        or (existing_folder_count >= 5 and scanned_folder_count * 2 < existing_folder_count)
    ):
        remove_missing = False
        if progress_callback:
            progress_callback(
                f"Catalog cleanup skipped: scan found {scanned_folder_count} folder(s) "
                f"but the catalog has {existing_folder_count}; existing entries were preserved"
            )

    season_rows = fetchall("SELECT id, rel_path, enabled FROM seasons") if remove_missing else []
    stale_seasons = [row for row in season_rows if row["rel_path"] not in live_seasons and row["enabled"]]
    excluded_missing_seasons = [row for row in season_rows if row["rel_path"] not in live_seasons and not row["enabled"]]
    stale_movies = [row for row in fetchall("SELECT id, rel_path FROM movies") if row["rel_path"] not in live_movies] if remove_missing else []
    stale_series = [row for row in fetchall("SELECT id, title FROM series") if row["id"] not in series_ids] if remove_missing else []

    with transaction() as conn:
        for row in stale_seasons:
            for table in ("files", "attempts", "episode_watch_state", "owner_state"):
                conn.execute(f"DELETE FROM {table} WHERE owner_kind='season' AND owner_id=?", (row["id"],))
            conn.execute("DELETE FROM seasons WHERE id=?", (row["id"],))
        for row in excluded_missing_seasons:
            conn.execute("DELETE FROM files WHERE owner_kind='season' AND owner_id=?", (row["id"],))
            conn.execute("UPDATE seasons SET sync_mtime_ns=NULL WHERE id=?", (row["id"],))
        for row in stale_movies:
            for table in ("files", "attempts", "episode_watch_state", "owner_state"):
                conn.execute(f"DELETE FROM {table} WHERE owner_kind='movie' AND owner_id=?", (row["id"],))
            conn.execute("DELETE FROM movies WHERE id=?", (row["id"],))
        for row in stale_series:
            if conn.execute("SELECT 1 FROM seasons WHERE series_id=? LIMIT 1", (row["id"],)).fetchone():
                continue
            conn.execute("DELETE FROM calendar_episodes WHERE series_id=?", (row["id"],))
            conn.execute("DELETE FROM calendar_sync WHERE series_id=?", (row["id"],))
            conn.execute("DELETE FROM series WHERE id=?", (row["id"],))
        conn.execute(
            "UPDATE series SET latest_season=COALESCE((SELECT MAX(season) FROM seasons WHERE seasons.series_id=series.id),0)"
        )

    if progress_callback:
        progress_callback(
            f"Catalog reconciled: {len(live_seasons)} season(s), {len(live_movies)} movie(s), "
            f"{len(stale_seasons) + len(stale_movies)} removed folder(s)"
        )
