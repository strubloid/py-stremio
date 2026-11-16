"""Migration from per-folder JSON to SQLite catalog."""
from __future__ import annotations
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from py_stremio.components.configs.config_file import DownloadConfig
    from py_stremio.components.state.app_state import DownloadState

from py_stremio.components.library.library_scanner import Scanner, FolderType
from py_stremio.storage.catalog import (
    get_or_create_series,
    get_or_create_season,
    get_or_create_movie,
    get_season_by_rel_path,
    get_movie_by_rel_path,
    upsert_files,
    set_season_metadata_due,
    set_movie_metadata_due,
    update_season_inventory_synced,
    update_movie_inventory_synced,
)
from py_stremio.storage.db import init_db, transaction, execute
from py_stremio.utils.media import parse_season_from_folder


def migrate(root_folder: Path | None = None, db_path: Path | None = None, dry_run: bool = False) -> dict[str, int]:
    """Migrate all JSON configs/states to SQLite catalog.

    Args:
        root_folder: Root media folder (defaults to settings.ROOT_FOLDER)
        db_path: Database path (defaults to PY_STREMIO_DB or ~/.local/share/py-stremio/library.sqlite)
        dry_run: If True, only report what would be migrated without writing

    Returns:
        Dict with counts: {"series": n, "seasons": n, "movies": n, "files": n, "states": n}
    """
    if root_folder is None:
        from py_stremio.components.configs.app_settings import settings
        root_folder = settings.ROOT_FOLDER

    if db_path is not None:
        os.environ["PY_STREMIO_DB"] = str(db_path)

    # Initialize database
    if not dry_run:
        from py_stremio.storage.db import close_connection

        close_connection()
        init_db()
        execute("UPDATE meta SET value = ? WHERE key = 'media_root'", (str(root_folder),))

    scanner = Scanner()
    scanner.root = root_folder
    scanner.series_root = root_folder / "series"
    scanner.movies_root = root_folder / "movies"
    if not dry_run:
        scanner.ensure_folders()
    folders = scanner.scan()

    counts = {"series": 0, "seasons": 0, "movies": 0, "files": 0, "states": 0}
    series_seen: set[int] = set()

    for folder in folders:
        if folder.folder_type == FolderType.SERIES:
            _migrate_season_folder(folder, counts, series_seen, dry_run)
        elif folder.folder_type == FolderType.MOVIES:
            _migrate_movie_folder(folder, counts, dry_run)

    if not dry_run:
        # Update series latest_season
        for series_id in series_seen:
            _update_series_latest_season(series_id)
        if counts["seasons"] or counts["movies"]:
            with transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta (key, value) VALUES ('migration_complete', '1')"
                )

    return counts


def _migrate_season_folder(folder, counts: dict, series_seen: set[int], dry_run: bool) -> None:
    """Migrate a single season folder."""
    rel_path = str(folder.path.relative_to(folder.path.parents[2]))  # series/Show/sXX
    series_rel = str(folder.path.parent.relative_to(folder.path.parents[2]))  # series/Show
    series_title = folder.path.parent.name.replace("-", " ").replace("_", " ").title()
    season_num = folder.season_number or 1

    # Load JSON config and state
    from py_stremio.components.configs.config_file import _load_config_json as load_json_config
    from py_stremio.components.state.app_state import _load_state_json as load_json_state
    config, config_path = load_json_config(folder.path)
    state = load_json_state(folder.path)

    if dry_run:
        print(f"  [dry-run] Would migrate season: {series_title} S{season_num:02d}")
        counts["seasons"] += 1
        counts["states"] += 1
        return

    with transaction() as conn:
        # Create/update series
        series_id = get_or_create_series(series_title, series_rel, config.imdb_id)
        if series_id not in series_seen:
            counts["series"] += 1
        series_seen.add(series_id)

        # Create/update season
        season_id = get_or_create_season(series_id, season_num, rel_path, _config_to_dict(config))

        # Persist config to DB (overrides any defaults from get_or_create_season)
        _save_config_to_db(conn, season_id, config, "season")

        # Persist state to DB
        _save_state_to_db(conn, season_id, state, "season")

        # Inventory files
        files = _inventory_files(folder.path, config.episode_count or 0, season_num)
        upsert_files("season", season_id, files)
        update_season_inventory_synced(season_id, folder.path.stat().st_mtime_ns)
        season_row = get_season_by_rel_path(rel_path)
        due_at = _metadata_due_at(config.metadata_last_checked) if season_row and season_row["poster_url"] else datetime.now(timezone.utc).isoformat()
        set_season_metadata_due(season_id, due_at)
        counts["files"] += len(files)

        counts["seasons"] += 1
        counts["states"] += 1


def _migrate_movie_folder(folder, counts: dict, dry_run: bool) -> None:
    """Migrate a single movie folder."""
    rel_path = str(folder.path.relative_to(folder.path.parents[1]))  # movies/Title
    from py_stremio.components.configs.config_file import _load_config_json as load_json_config
    from py_stremio.components.state.app_state import _load_state_json as load_json_state
    config, config_path = load_json_config(folder.path)
    state = load_json_state(folder.path)

    if dry_run:
        print(f"  [dry-run] Would migrate movie: {folder.path.name}")
        counts["movies"] += 1
        counts["states"] += 1
        return

    with transaction() as conn:
        movie_id = get_or_create_movie(
            config.title or folder.path.name,
            rel_path,
            config.imdb_id,
            _config_to_dict(config),
        )
        _save_config_to_db(conn, movie_id, config, "movie")
        _save_state_to_db(conn, movie_id, state, "movie")

        files = _inventory_movie_files(folder.path)
        upsert_files("movie", movie_id, files)
        update_movie_inventory_synced(movie_id, folder.path.stat().st_mtime_ns)
        movie_row = get_movie_by_rel_path(rel_path)
        due_at = _metadata_due_at(config.metadata_last_checked) if movie_row and movie_row["poster_url"] else datetime.now(timezone.utc).isoformat()
        set_movie_metadata_due(movie_id, due_at)
        counts["files"] += len(files)

        counts["movies"] += 1
        counts["states"] += 1


def _config_to_dict(config: DownloadConfig) -> dict[str, Any]:
    """Convert DownloadConfig to dict for database."""
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


def _save_config_to_db(conn, owner_id: int, config: DownloadConfig, kind: str) -> None:
    """Save config dict to database within transaction."""
    data = _config_to_dict(config)
    import json as json_mod

    # Movies don't have episode fields
    if kind == "movie":
        data.pop("episode_count", None)
        data.pop("available_episodes", None)
        data.pop("current_episode_download", None)
        data.pop("download_all_related", None)
        data.pop("experimental_addons_enabled", None)

    if kind == "season":
        updates = []
        params = []
        for key, value in data.items():
            if key in ("available_episodes", "quality", "languages", "servers", "disabled_servers", "working_addons"):
                value = json_mod.dumps(value) if value is not None else None
            elif key in ("enabled", "download_all_related", "experimental_addons_enabled"):
                value = 1 if value else 0
            updates.append(f"{key} = ?")
            params.append(value)
        if updates:
            params.append(owner_id)
            conn.execute(f"UPDATE seasons SET {', '.join(updates)} WHERE id = ?", params)
    else:
        updates = []
        params = []
        for key, value in data.items():
            if key in ("quality", "languages", "servers", "disabled_servers", "working_addons"):
                value = json_mod.dumps(value) if value is not None else None
            elif key == "enabled":
                value = 1 if value else 0
            updates.append(f"{key} = ?")
            params.append(value)
        if updates:
            params.append(owner_id)
            conn.execute(f"UPDATE movies SET {', '.join(updates)} WHERE id = ?", params)


def _save_state_to_db(conn, owner_id: int, state, kind: str) -> None:
    """Save state to database within transaction."""
    owner_kind = "season" if kind == "season" else "movie"
    now = datetime.now(timezone.utc).isoformat()
    state_data = {
        "items": {key: vars(record) for key, record in state.items.items()},
        "last_scan": state.last_scan,
        "total_downloaded": state.total_downloaded,
        "failed_items": state.failed_items,
        "preflight_indeterminate": state.preflight_indeterminate,
        "in_progress": state.in_progress,
        "started": state.started,
    }
    conn.execute(
        """INSERT OR REPLACE INTO owner_state (owner_kind, owner_id, state_json, updated_at)
           VALUES (?, ?, ?, ?)""",
        (owner_kind, owner_id, json.dumps(state_data), now),
    )

    # Downloaded items
    for filename, record in state.items.items():
        ep = _episode_from_filename(filename) if kind == "season" else None
        conn.execute(
            """INSERT OR REPLACE INTO attempts
               (owner_kind, owner_id, episode, started_at, completed_at, success, server_url, error, bytes, quality)
               VALUES (?, ?, ?, ?, ?, 1, ?, '', 0, ?)""",
            (owner_kind, owner_id, ep, record.timestamp, record.timestamp, record.server or record.addon_url, record.quality),
        )

    # Failed items
    for key, fail_data in state.failed_items.items():
        ep = _episode_from_filename(key) if kind == "season" else None
        conn.execute(
            """INSERT OR REPLACE INTO attempts
               (owner_kind, owner_id, episode, started_at, completed_at, success, server_url, error, bytes, quality)
               VALUES (?, ?, ?, ?, ?, 0, '', ?, 0, '')""",
            (owner_kind, owner_id, ep, fail_data.get("timestamp", now), fail_data.get("timestamp", now), fail_data.get("error", "unknown")),
        )

    # In-progress
    for key, prog_data in state.in_progress.items():
        ep = _episode_from_filename(key) if kind == "season" else None
        conn.execute(
            """INSERT OR REPLACE INTO attempts
               (owner_kind, owner_id, episode, started_at, success, server_url, bytes, quality)
               VALUES (?, ?, ?, ?, 0, '', ?, '')""",
            (owner_kind, owner_id, ep, prog_data.get("started_at", now), prog_data.get("part_bytes", 0)),
        )

    # Started (priority)
    for key, start_data in state.started.items():
        ep = _episode_from_filename(key) if kind == "season" else None
        conn.execute(
            """INSERT OR REPLACE INTO attempts
               (owner_kind, owner_id, episode, started_at, completed_at, success, server_url, bytes, quality)
               VALUES (?, ?, ?, ?, 1, ?, ?, '')""",
            (owner_kind, owner_id, ep, start_data.get("started_at", now), start_data.get("started_at", now), start_data.get("server", ""), start_data.get("bytes_at_first_arrival", 0)),
        )


def _inventory_files(folder_path: Path, episode_count: int, season: int) -> list[dict]:
    """Scan folder for video files and build file inventory."""
    from py_stremio.components.library.media_file import scan_episode_files
    files = []
    for media_file in scan_episode_files(folder_path):
        is_part = media_file.path.suffix == ".part"
        files.append({
            "rel_path": media_file.path.name,
            "episode": media_file.episode,
            "size": media_file.path.stat().st_size if media_file.path.exists() else 0,
            "mtime_ns": int(media_file.path.stat().st_mtime_ns) if media_file.path.exists() else 0,
            "is_part": is_part,
        })
    return files


def _inventory_movie_files(folder_path: Path) -> list[dict]:
    """Scan movie folder for video file."""
    from py_stremio.components.library.media_file import iter_video_files
    files = []
    for media_file in iter_video_files(folder_path):
        # iter_video_files returns Path objects directly
        is_part = media_file.suffix == ".part"
        files.append({
            "rel_path": media_file.name,
            "episode": None,
            "size": media_file.stat().st_size if media_file.exists() else 0,
            "mtime_ns": int(media_file.stat().st_mtime_ns) if media_file.exists() else 0,
            "is_part": is_part,
        })
    return files


def _episode_from_filename(filename: str) -> int | None:
    """Extract episode number from filename."""
    import re
    match = re.search(r"[sS]\d+[eE](\d+)", filename)
    if match:
        return int(match.group(1))
    match = re.search(r"episode[_-]?(\d+)", filename, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _metadata_due_at(checked_at: str | None) -> str:
    from py_stremio.components.configs.app_settings import settings

    now = datetime.now(timezone.utc)
    try:
        checked = datetime.fromisoformat(str(checked_at).replace("Z", "+00:00"))
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        return (checked + timedelta(hours=settings.CONFIGS_CACHE_HOURS)).isoformat()
    except (TypeError, ValueError):
        return now.isoformat()


def _update_series_latest_season(series_id: int) -> None:
    """Update series latest_season from seasons table."""
    row = execute(
        "SELECT MAX(season) as max_season FROM seasons WHERE series_id = ?",
        (series_id,),
    ).fetchone()
    if row and row["max_season"]:
        execute(
            "UPDATE series SET latest_season = ? WHERE id = ?",
            (row["max_season"], series_id),
        )


def export_json(folder_path: Path, output_dir: Path) -> None:
    """Export a folder's config/state from SQLite back to JSON (for debugging/rollback)."""
    from py_stremio.storage.repositories import SeasonRepo, MovieRepo
    from py_stremio.components.configs.app_settings import settings
    from py_stremio.components.configs.config_file import is_series_season_folder

    rel_path = folder_path.relative_to(settings.ROOT_FOLDER)
    # Determine if series or movie
    if is_series_season_folder(folder_path):
        repo = SeasonRepo.from_folder(folder_path, settings.ROOT_FOLDER)
        config_path = output_dir / "download-config.json"
        state_path = output_dir / ".download-state.json"
    else:
        repo = MovieRepo.from_folder(folder_path, settings.ROOT_FOLDER)
        config_path = output_dir / "download-config.json"
        state_path = output_dir / ".download-state.json"

    # Write config
    from py_stremio.utils.atomic_write import atomic_write_json
    from dataclasses import asdict
    config_data = asdict(repo.config)
    atomic_write_json(config_path, config_data, indent=2)

    # Write state
    state_data = {
        "items": {k: asdict(v) for k, v in repo.state.items.items()},
        "last_scan": repo.state.last_scan,
        "total_downloaded": repo.state.total_downloaded,
        "failed_items": repo.state.failed_items,
        "preflight_indeterminate": repo.state.preflight_indeterminate,
        "in_progress": repo.state.in_progress,
        "started": repo.state.started,
    }
    atomic_write_json(state_path, state_data, indent=2)
