"""Repository classes - drop-in replacements for load_config/load_state with SQLite backend."""
from __future__ import annotations
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from py_stremio.components.configs.config_file import DownloadConfig, QualitySettings
from py_stremio.components.state.app_state import DownloadState, DownloadRecord
from py_stremio.storage.catalog import (
    get_or_create_season,
    get_or_create_movie,
    get_or_create_series,
    get_season_by_rel_path,
    get_movie_by_rel_path,
    get_series_by_rel_path,
    update_season_inventory_synced,
    update_movie_inventory_synced,
    set_season_metadata_due,
    set_movie_metadata_due,
    upsert_files,
    get_files,
    get_downloaded_episodes,
    get_missing_episodes,
    upsert_addon,
    get_addon_status,
)
from py_stremio.storage.db import transaction, execute, fetchone, init_db
from py_stremio.utils.media import parse_season_from_folder


@dataclass
class SeasonRepo:
    """Repository for season folder config + state (replaces load_config + load_state)."""
    season_id: int
    config: DownloadConfig
    state: DownloadState
    rel_path: str
    series_title: str
    series_imdb_id: str | None

    @classmethod
    def from_folder(cls, folder_path: Path, media_root: Path) -> "SeasonRepo":
        """Load or create repo for a season folder."""
        init_db()
        rel_path = str(folder_path.relative_to(media_root))
        series_rel = str(folder_path.parent.relative_to(media_root))
        series_title = folder_path.parent.name.replace("-", " ").replace("_", " ").title()
        season_num = parse_season_from_folder(folder_path.name) or 1
        season_row = get_season_by_rel_path(rel_path)
        if season_row:
            season_id = season_row["id"]
            series_id = season_row["series_id"]
            config = _config_from_row(season_row, "season")
        else:
            config = _load_legacy_or_default_config(folder_path)
            series_id = get_or_create_series(series_title, series_rel, config.imdb_id)
            season_id = get_or_create_season(series_id, season_num, rel_path, _config_to_dict(config))
            season_row = get_season_by_rel_path(rel_path)

        state = _load_state_from_db("season", season_id, folder_path)
        series_row = fetchone("SELECT title, imdb_id FROM series WHERE id = ?", (series_id,))
        series_title = series_row["title"] if series_row else series_title
        series_imdb_id = series_row["imdb_id"] if series_row else None
        config.title = series_title
        config.imdb_id = series_imdb_id

        return cls(
            season_id=season_id,
            config=config,
            state=state,
            rel_path=rel_path,
            series_title=series_title,
            series_imdb_id=series_imdb_id,
        )

    def save_config(self) -> None:
        """Persist config to database."""
        _save_config_to_db(self.season_id, self.config, "season")

    def save_state(self) -> None:
        """Persist state to database."""
        _save_state_to_db(self.season_id, self.state, "season")

    def mark_inventory_synced(self, mtime_ns: int) -> None:
        update_season_inventory_synced(self.season_id, mtime_ns)

    def mark_metadata_due(self, due_at: str | None = None) -> None:
        set_season_metadata_due(self.season_id, due_at)

    def sync_files(self, files: list[dict]) -> None:
        upsert_files("season", self.season_id, files)

    def get_downloaded_episodes(self) -> set[int]:
        return get_downloaded_episodes("season", self.season_id)

    def get_missing_episodes(self) -> list[int]:
        missing = get_missing_episodes(self.season_id)
        return [m.episode for m in missing]


@dataclass
class MovieRepo:
    """Repository for movie folder config + state."""
    movie_id: int
    config: DownloadConfig
    state: DownloadState
    rel_path: str

    @classmethod
    def from_folder(cls, folder_path: Path, media_root: Path) -> "MovieRepo":
        init_db()
        rel_path = str(folder_path.relative_to(media_root))
        movie_row = get_movie_by_rel_path(rel_path)
        if movie_row:
            movie_id = movie_row["id"]
            config = _config_from_row(movie_row, "movie")
        else:
            config = _load_legacy_or_default_config(folder_path)
            movie_id = get_or_create_movie(
                config.title or folder_path.name,
                rel_path,
                config.imdb_id,
                _config_to_dict(config),
            )
        state = _load_state_from_db("movie", movie_id, folder_path)
        return cls(movie_id=movie_id, config=config, state=state, rel_path=rel_path)

    def save_config(self) -> None:
        _save_config_to_db(self.movie_id, self.config, "movie")

    def save_state(self) -> None:
        _save_state_to_db(self.movie_id, self.state, "movie")

    def mark_inventory_synced(self, mtime_ns: int) -> None:
        update_movie_inventory_synced(self.movie_id, mtime_ns)

    def mark_metadata_due(self, due_at: str | None = None) -> None:
        set_movie_metadata_due(self.movie_id, due_at)

    def sync_files(self, files: list[dict]) -> None:
        upsert_files("movie", self.movie_id, files)

    def get_downloaded_files(self) -> set[str]:
        return {f["rel_path"] for f in get_files("movie", self.movie_id) if not f["is_part"]}


# ── JSON shims (backward compat) ────────────────────────────────────────────

def _load_json_config(folder_path: Path) -> tuple[DownloadConfig, Path]:
    """Load config from JSON file (legacy path)."""
    from py_stremio.components.configs.config_file import _load_config_json as load_json_config
    return load_json_config(folder_path)


def _load_json_state(folder_path: Path) -> DownloadState:
    """Load state from JSON file (legacy path)."""
    from py_stremio.components.state.app_state import _load_state_json as load_json_state
    return load_json_state(folder_path)


def _load_legacy_or_default_config(folder_path: Path) -> DownloadConfig:
    config_path = folder_path / "download-config.json"
    if config_path.exists():
        return _load_json_config(folder_path)[0]
    from py_stremio.components.configs.config_file import get_default_config

    return get_default_config(folder_path)


def _config_from_row(row: dict, kind: str) -> DownloadConfig:
    values = {key: json.loads(row[key]) if row.get(key) else None for key in (
        "quality", "languages", "available_episodes", "servers", "disabled_servers", "working_addons"
    ) if key in row}
    quality_data = values.get("quality")
    return DownloadConfig(
        type="series" if kind == "season" else "movies",
        title=row.get("title") or row.get("series_title"),
        imdb_id=row.get("imdb_id"),
        season=row.get("season") if kind == "season" else None,
        episode_count=row.get("episode_count") if kind == "season" else None,
        available_episodes=values.get("available_episodes"),
        current_episode_download=row.get("current_episode_download", 0 if kind == "movie" else 1),
        enabled=bool(row.get("enabled", True)),
        quality=QualitySettings(**quality_data) if quality_data else QualitySettings(),
        languages=values.get("languages"),
        subtitles=row.get("subtitles") or "english",
        provider=row.get("provider") or "auto",
        search_group=row.get("search_group"),
        download_all_related=bool(row.get("download_all_related", True)),
        working_addons=values.get("working_addons") or [],
        servers=values.get("servers") or [],
        disabled_servers=values.get("disabled_servers") or [],
        metadata_last_checked=row.get("metadata_last_checked"),
        experimental_addons_enabled=bool(row.get("experimental_addons_enabled", True)),
    )


def _state_to_dict(state: DownloadState) -> dict:
    return {
        "items": {key: asdict(record) for key, record in state.items.items()},
        "last_scan": state.last_scan,
        "total_downloaded": state.total_downloaded,
        "failed_items": state.failed_items,
        "preflight_indeterminate": state.preflight_indeterminate,
        "in_progress": state.in_progress,
        "started": state.started,
    }


def _state_from_dict(folder_path: Path, data: dict) -> DownloadState:
    records = {
        name: DownloadRecord(**record)
        for name, record in data.get("items", {}).items()
    }
    return DownloadState(
        folder_path=folder_path,
        items=records,
        last_scan=data.get("last_scan", ""),
        total_downloaded=data.get("total_downloaded", 0),
        failed_items=data.get("failed_items", {}),
        preflight_indeterminate=data.get("preflight_indeterminate", {}),
        in_progress=data.get("in_progress", {}),
        started=data.get("started", {}),
    )


def _load_state_from_db(owner_kind: str, owner_id: int, folder_path: Path) -> DownloadState:
    row = fetchone(
        "SELECT state_json FROM owner_state WHERE owner_kind = ? AND owner_id = ?",
        (owner_kind, owner_id),
    )
    if row:
        return _state_from_dict(folder_path, json.loads(row["state_json"]))
    state = _load_json_state(folder_path) if (folder_path / ".download-state.json").exists() else DownloadState(folder_path)
    _save_state_to_db(owner_id, state, owner_kind)
    return state


def _config_to_dict(config: DownloadConfig) -> dict:
    """Convert DownloadConfig to dict for database storage."""
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


def _save_config_to_db(owner_id: int, config: DownloadConfig, kind: str) -> None:
    """Save config to database."""
    data = _config_to_dict(config)
    now = datetime.now(timezone.utc).isoformat()

    with transaction() as conn:
        if kind == "season":
            updates = []
            params = []
            for key, value in data.items():
                if key in ("available_episodes", "quality", "languages", "servers", "disabled_servers", "working_addons"):
                    value = json.dumps(value) if value is not None else None
                elif key in ("enabled", "download_all_related", "experimental_addons_enabled"):
                    value = 1 if value else 0
                updates.append(f"{key} = ?")
                params.append(value)
            if updates:
                params.append(owner_id)
                conn.execute(f"UPDATE seasons SET {', '.join(updates)} WHERE id = ?", params)
                conn.execute(
                    """UPDATE series SET title = COALESCE(?, title), imdb_id = COALESCE(?, imdb_id), updated_at = ?
                       WHERE id = (SELECT series_id FROM seasons WHERE id = ?)""",
                    (config.title, config.imdb_id, now, owner_id),
                )
        else:
            updates = []
            params = []
            for key, value in data.items():
                if key in ("quality", "languages", "servers", "disabled_servers", "working_addons"):
                    value = json.dumps(value) if value is not None else None
                elif key == "enabled":
                    value = 1 if value else 0
                updates.append(f"{key} = ?")
                params.append(value)
            if updates:
                params.append(owner_id)
                conn.execute(f"UPDATE movies SET {', '.join(updates)} WHERE id = ?", params)


def _save_state_to_db(owner_id: int, state: DownloadState, kind: str) -> None:
    """Save state to database (items, failed, in_progress, started)."""
    now = datetime.now(timezone.utc).isoformat()
    owner_kind = "season" if kind == "season" else "movie"

    with transaction() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO owner_state (owner_kind, owner_id, state_json, updated_at)
               VALUES (?, ?, ?, ?)""",
            (owner_kind, owner_id, json.dumps(_state_to_dict(state)), now),
        )
        # Save downloaded items as attempts with success=1
        for filename, record in state.items.items():
            conn.execute(
                """INSERT OR REPLACE INTO attempts
                   (owner_kind, owner_id, episode, started_at, completed_at, success, server_url, error, bytes, quality)
                   VALUES (?, ?, ?, ?, ?, 1, ?, '', 0, ?)""",
                (
                    owner_kind,
                    owner_id,
                    _episode_from_filename(filename),
                    record.timestamp,
                    record.timestamp,
                    record.server or record.addon_url,
                    record.quality,
                ),
            )

        # Save failed items
        for key, fail_data in state.failed_items.items():
            ep = _episode_from_filename(key)
            conn.execute(
                """INSERT OR REPLACE INTO attempts
                   (owner_kind, owner_id, episode, started_at, completed_at, success, server_url, error, bytes, quality)
                   VALUES (?, ?, ?, ?, ?, 0, '', ?, 0, '')""",
                (
                    owner_kind,
                    owner_id,
                    ep,
                    fail_data.get("timestamp", now),
                    fail_data.get("timestamp", now),
                    fail_data.get("error", "unknown"),
                ),
            )

        # Save in_progress
        for key, prog_data in state.in_progress.items():
            ep = _episode_from_filename(key)
            conn.execute(
                """INSERT OR REPLACE INTO attempts
                   (owner_kind, owner_id, episode, started_at, success, server_url, bytes, quality)
                   VALUES (?, ?, ?, ?, 0, '', ?, '')""",
                (
                    owner_kind,
                    owner_id,
                    ep,
                    prog_data.get("started_at", now),
                    prog_data.get("part_bytes", 0),
                ),
            )

        # Save started (priority list)
        for key, start_data in state.started.items():
            ep = _episode_from_filename(key)
            conn.execute(
                """INSERT OR REPLACE INTO attempts
                   (owner_kind, owner_id, episode, started_at, completed_at, success, server_url, bytes, quality)
                   VALUES (?, ?, ?, ?, 1, ?, ?, '')""",
                (
                    owner_kind,
                    owner_id,
                    ep,
                    start_data.get("started_at", now),
                    start_data.get("started_at", now),
                    start_data.get("server", ""),
                    start_data.get("bytes_at_first_arrival", 0),
                ),
            )


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


# ── Addon repository ────────────────────────────────────────────────────────

class AddonRepo:
    """Repository for addon URL tracking."""

    @staticmethod
    def mark_working(url: str) -> None:
        upsert_addon(url, "working", download_completed=True)

    @staticmethod
    def mark_tested_working(url: str) -> None:
        upsert_addon(url, "working")

    @staticmethod
    def mark_failed(url: str, error: str) -> None:
        upsert_addon(url, "failed", error)

    @staticmethod
    def mark_untested(url: str) -> None:
        upsert_addon(url, "untested")

    @staticmethod
    def get_status(url: str) -> str | None:
        return get_addon_status(url)

    @staticmethod
    def get_working(limit: int = 50) -> list[str]:
        from py_stremio.storage.catalog import get_working_addons
        return get_working_addons(limit)
