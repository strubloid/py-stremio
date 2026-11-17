"""Catalog query builders - high-level queries against the SQLite catalog."""
from __future__ import annotations
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from py_stremio.storage.db import (
    execute,
    fetchone,
    fetchall,
    transaction,
    get_connection,
)


@dataclass
class MissingEpisode:
    season_id: int
    series_id: int
    series_title: str
    season: int
    episode: int
    rel_path: str
    imdb_id: str | None
    quality: str | None
    languages: list[str] | None
    subtitles: str | None
    provider: str | None
    servers: list[str]
    disabled_servers: list[str]
    working_addons: list[str]
    experimental_addons_enabled: bool


@dataclass
class StaleFolder:
    kind: str  # 'season' or 'movie'
    id: int
    rel_path: str
    reason: str  # 'inventory', 'metadata', 'structure'


@dataclass
class FolderInventory:
    kind: str
    id: int
    rel_path: str
    files: list[dict]  # {rel_path, episode, size, mtime_ns, is_part}


# ── Series queries ──────────────────────────────────────────────────────────

def get_series_by_rel_path(rel_path: str) -> dict | None:
    """Get series by relative path."""
    row = fetchone("SELECT * FROM series WHERE rel_path = ?", (rel_path,))
    return dict(row) if row else None


def get_or_create_series(title: str, rel_path: str, imdb_id: str | None = None) -> int:
    """Get series ID, creating if needed. Returns series_id."""
    now = datetime.now(timezone.utc).isoformat()
    with transaction() as conn:
        row = conn.execute(
            "SELECT id FROM series WHERE rel_path = ?", (rel_path,)
        ).fetchone()
        if row:
            series_id = row["id"]
            # Update title/imdb_id if provided
            updates = []
            params = []
            if title:
                updates.append("title = ?")
                params.append(title)
            if imdb_id:
                updates.append("imdb_id = ?")
                params.append(imdb_id)
            if updates:
                updates.append("updated_at = ?")
                params.append(now)
                params.append(series_id)
                conn.execute(f"UPDATE series SET {', '.join(updates)} WHERE id = ?", params)
            return series_id
        cursor = conn.execute(
            "INSERT INTO series (title, imdb_id, rel_path, latest_season, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            (title, imdb_id, rel_path, now, now),
        )
        return cursor.lastrowid


def update_series_latest_season(series_id: int, season: int) -> None:
    """Update the latest_season for a series."""
    now = datetime.now(timezone.utc).isoformat()
    execute(
        "UPDATE series SET latest_season = MAX(latest_season, ?), updated_at = ? WHERE id = ?",
        (season, now, series_id),
    )


def update_series_artwork(series_id: int, poster_url: str | None, background_url: str | None = None) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE series SET poster_url=COALESCE(?,poster_url), background_url=COALESCE(?,background_url) WHERE id=?",
            (poster_url, background_url, series_id),
        )


def update_season_artwork(season_id: int, poster_url: str | None) -> None:
    if not poster_url:
        return
    with transaction() as conn:
        conn.execute("UPDATE seasons SET poster_url=? WHERE id=?", (poster_url, season_id))


def update_movie_artwork(
    movie_id: int,
    poster_url: str | None,
    background_url: str | None = None,
    release_date: str | None = None,
) -> None:
    if not poster_url and not background_url and not release_date:
        return
    with transaction() as conn:
        conn.execute(
            """UPDATE movies SET poster_url=COALESCE(?,poster_url),
                      background_url=COALESCE(?,background_url),
                      release_date=COALESCE(?,release_date) WHERE id=?""",
            (poster_url, background_url, release_date, movie_id),
        )


def get_all_series() -> list[dict]:
    """Get all series with their latest season."""
    rows = fetchall("SELECT * FROM series ORDER BY title")
    return [dict(r) for r in rows]


# ── Season queries ──────────────────────────────────────────────────────────

def get_season_by_rel_path(rel_path: str) -> dict | None:
    """Get season by relative path."""
    row = fetchone("SELECT * FROM seasons WHERE rel_path = ?", (rel_path,))
    return dict(row) if row else None


def get_seasons_for_series(series_id: int) -> list[dict]:
    """Get all seasons for a series."""
    rows = fetchall("SELECT * FROM seasons WHERE series_id = ? ORDER BY season", (series_id,))
    return [dict(r) for r in rows]


def get_or_create_season(
    series_id: int,
    season: int,
    rel_path: str,
    config: dict | None = None,
) -> int:
    """Get or create a season row. Returns season_id."""
    now = datetime.now(timezone.utc).isoformat()
    with transaction() as conn:
        row = conn.execute(
            "SELECT id FROM seasons WHERE series_id = ? AND season = ?", (series_id, season)
        ).fetchone()
        if row:
            season_id = row["id"]
            if config:
                _update_season_config(conn, season_id, config)
            return season_id
        cursor = conn.execute(
            """INSERT INTO seasons (
                series_id, season, rel_path, episode_count, available_episodes,
                current_episode_download, enabled, quality, languages, subtitles,
                provider, search_group, download_all_related, servers,
                disabled_servers, working_addons, experimental_addons_enabled,
                metadata_last_checked, metadata_due_at, sync_mtime_ns, last_inventoried_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                series_id,
                season,
                rel_path,
                config.get("episode_count") if config else None,
                json.dumps(config.get("available_episodes")) if config and config.get("available_episodes") else None,
                config.get("current_episode_download", 1) if config else 1,
                1 if config and config.get("enabled") else 1,
                json.dumps(config.get("quality")) if config and config.get("quality") else None,
                json.dumps(config.get("languages")) if config and config.get("languages") else None,
                config.get("subtitles") if config else None,
                config.get("provider") if config else None,
                config.get("search_group") if config else None,
                1 if config and config.get("download_all_related") else 1,
                json.dumps(config.get("servers")) if config and config.get("servers") else "[]",
                json.dumps(config.get("disabled_servers")) if config and config.get("disabled_servers") else "[]",
                json.dumps(config.get("working_addons")) if config and config.get("working_addons") else "[]",
                1 if config and config.get("experimental_addons_enabled") else 1,
                config.get("metadata_last_checked") if config else None,
                None,  # metadata_due_at
                None,  # sync_mtime_ns
                now,
            ),
        )
        return cursor.lastrowid


def _update_season_config(conn: sqlite3.Connection, season_id: int, config: dict) -> None:
    """Update season config fields."""
    now = datetime.now(timezone.utc).isoformat()
    updates = []
    params = []
    for key, value in config.items():
        if key in (
            "episode_count", "available_episodes", "current_episode_download",
            "enabled", "quality", "languages", "subtitles", "provider",
            "search_group", "download_all_related", "servers",
            "disabled_servers", "working_addons", "experimental_addons_enabled",
            "metadata_last_checked",
        ):
            if key in ("available_episodes", "quality", "languages", "servers", "disabled_servers", "working_addons"):
                value = json.dumps(value) if value is not None else None
            elif key in ("enabled", "download_all_related", "experimental_addons_enabled"):
                value = 1 if value else 0
            updates.append(f"{key} = ?")
            params.append(value)
    if updates:
        updates.append("updated_at = ?")
        params.append(now)
        params.append(season_id)
        conn.execute(f"UPDATE seasons SET {', '.join(updates)} WHERE id = ?", params)


def update_season_inventory_synced(season_id: int, mtime_ns: int) -> None:
    """Mark season inventory as synced with disk."""
    now = datetime.now(timezone.utc).isoformat()
    execute(
        "UPDATE seasons SET sync_mtime_ns = ?, last_inventoried_at = ? WHERE id = ?",
        (mtime_ns, now, season_id),
    )


def set_season_metadata_due(season_id: int, due_at: str | None = None) -> None:
    """Set metadata_due_at for a season (None = now)."""
    if due_at is None:
        due_at = datetime.now(timezone.utc).isoformat()
    execute("UPDATE seasons SET metadata_due_at = ? WHERE id = ?", (due_at, season_id))


def get_stale_seasons(now_iso: str | None = None) -> list[dict]:
    """Get seasons where metadata_due_at <= now."""
    if now_iso is None:
        now_iso = datetime.now(timezone.utc).isoformat()
    rows = fetchall(
        "SELECT * FROM seasons WHERE metadata_due_at IS NOT NULL AND metadata_due_at <= ?",
        (now_iso,),
    )
    return [dict(r) for r in rows]


def get_seasons_needing_inventory_sync() -> list[dict]:
    """Get seasons where folder mtime might have changed."""
    rows = fetchall("SELECT id, rel_path, sync_mtime_ns FROM seasons WHERE sync_mtime_ns IS NOT NULL")
    return [dict(r) for r in rows]


# ── Movie queries ───────────────────────────────────────────────────────────

def get_movie_by_rel_path(rel_path: str) -> dict | None:
    """Get movie by relative path."""
    row = fetchone("SELECT * FROM movies WHERE rel_path = ?", (rel_path,))
    return dict(row) if row else None


def get_or_create_movie(title: str, rel_path: str, imdb_id: str | None = None, config: dict | None = None) -> int:
    """Get or create a movie row. Returns movie_id."""
    now = datetime.now(timezone.utc).isoformat()
    with transaction() as conn:
        row = conn.execute("SELECT id FROM movies WHERE rel_path = ?", (rel_path,)).fetchone()
        if row:
            movie_id = row["id"]
            if config or imdb_id or title:
                _update_movie_config(conn, movie_id, config or {}, title, imdb_id)
            return movie_id
        cursor = conn.execute(
            """INSERT INTO movies (
                title, imdb_id, rel_path, enabled, quality, languages, subtitles,
                provider, servers, disabled_servers, working_addons,
                metadata_last_checked, metadata_due_at, sync_mtime_ns, last_inventoried_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                title,
                imdb_id,
                rel_path,
                1 if config and config.get("enabled") else 1,
                json.dumps(config.get("quality")) if config and config.get("quality") else None,
                json.dumps(config.get("languages")) if config and config.get("languages") else None,
                config.get("subtitles") if config else None,
                config.get("provider") if config else None,
                json.dumps(config.get("servers")) if config and config.get("servers") else "[]",
                json.dumps(config.get("disabled_servers")) if config and config.get("disabled_servers") else "[]",
                json.dumps(config.get("working_addons")) if config and config.get("working_addons") else "[]",
                config.get("metadata_last_checked") if config else None,
                None,  # metadata_due_at
                None,  # sync_mtime_ns
                now,
            ),
        )
        return cursor.lastrowid


def _update_movie_config(conn: sqlite3.Connection, movie_id: int, config: dict, title: str | None, imdb_id: str | None) -> None:
    """Update movie config fields."""
    now = datetime.now(timezone.utc).isoformat()
    updates = []
    params = []
    if title:
        updates.append("title = ?")
        params.append(title)
    if imdb_id:
        updates.append("imdb_id = ?")
        params.append(imdb_id)
    for key, value in config.items():
        if key in (
            "enabled", "quality", "languages", "subtitles", "provider",
            "servers", "disabled_servers", "working_addons", "metadata_last_checked",
        ):
            if key in ("quality", "languages", "servers", "disabled_servers", "working_addons"):
                value = json.dumps(value) if value is not None else None
            elif key == "enabled":
                value = 1 if value else 0
            updates.append(f"{key} = ?")
            params.append(value)
    if updates:
        params.append(movie_id)
        conn.execute(f"UPDATE movies SET {', '.join(updates)} WHERE id = ?", params)


def update_movie_inventory_synced(movie_id: int, mtime_ns: int) -> None:
    """Mark movie inventory as synced with disk."""
    now = datetime.now(timezone.utc).isoformat()
    execute(
        "UPDATE movies SET sync_mtime_ns = ?, last_inventoried_at = ? WHERE id = ?",
        (mtime_ns, now, movie_id),
    )


def set_movie_metadata_due(movie_id: int, due_at: str | None = None) -> None:
    """Set metadata_due_at for a movie."""
    if due_at is None:
        due_at = datetime.now(timezone.utc).isoformat()
    execute("UPDATE movies SET metadata_due_at = ? WHERE id = ?", (due_at, movie_id))


def get_stale_movies(now_iso: str | None = None) -> list[dict]:
    """Get movies where metadata_due_at <= now."""
    if now_iso is None:
        now_iso = datetime.now(timezone.utc).isoformat()
    rows = fetchall(
        "SELECT * FROM movies WHERE metadata_due_at IS NOT NULL AND metadata_due_at <= ?",
        (now_iso,),
    )
    return [dict(r) for r in rows]


# ── Files (inventory) ───────────────────────────────────────────────────────

def upsert_files(owner_kind: str, owner_id: int, files: list[dict]) -> None:
    """Replace file inventory for an owner (season or movie)."""
    with transaction() as conn:
        conn.execute(
            "DELETE FROM files WHERE owner_kind = ? AND owner_id = ?",
            (owner_kind, owner_id),
        )
        if files:
            conn.executemany(
                """INSERT INTO files (owner_kind, owner_id, rel_path, episode, size, mtime_ns, is_part)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        owner_kind,
                        owner_id,
                        f["rel_path"],
                        f.get("episode"),
                        f.get("size"),
                        f.get("mtime_ns"),
                        1 if f.get("is_part") else 0,
                    )
                    for f in files
                ],
            )


def get_files(owner_kind: str, owner_id: int) -> list[dict]:
    """Get all files for an owner."""
    rows = fetchall(
        "SELECT * FROM files WHERE owner_kind = ? AND owner_id = ? ORDER BY episode",
        (owner_kind, owner_id),
    )
    return [dict(r) for r in rows]


def get_downloaded_episodes(owner_kind: str, owner_id: int) -> set[int]:
    """Get set of episode numbers that have completed (non-part) files."""
    rows = fetchall(
        "SELECT DISTINCT episode FROM files WHERE owner_kind = ? AND owner_id = ? AND episode IS NOT NULL AND is_part = 0",
        (owner_kind, owner_id),
    )
    return {r["episode"] for r in rows}


# ── Missing episodes query ──────────────────────────────────────────────────

def get_missing_episodes(season_id: int) -> list[MissingEpisode]:
    """Get missing episodes for a season with all context needed for download."""
    season = fetchone("SELECT * FROM seasons WHERE id = ?", (season_id,))
    if not season:
        return []
    series = fetchone("SELECT * FROM series WHERE id = ?", (season["series_id"],))
    if not series:
        return []

    config = {
        "episode_count": season["episode_count"],
        "available_episodes": json.loads(season["available_episodes"] or "[]") if season["available_episodes"] else [],
        "quality": json.loads(season["quality"]) if season["quality"] else None,
        "languages": json.loads(season["languages"]) if season["languages"] else None,
        "subtitles": season["subtitles"],
        "provider": season["provider"],
        "servers": json.loads(season["servers"] or "[]") if season["servers"] else [],
        "disabled_servers": json.loads(season["disabled_servers"] or "[]") if season["disabled_servers"] else [],
        "working_addons": json.loads(season["working_addons"] or "[]") if season["working_addons"] else [],
        "experimental_addons_enabled": bool(season["experimental_addons_enabled"]),
    }

    have = get_downloaded_episodes("season", season_id)
    known = set(config["available_episodes"]) if config["available_episodes"] else set(range(1, (config["episode_count"] or 0) + 1))
    missing = sorted(known - have)

    if not missing:
        return []

    quality_pref = config["quality"].get("preferred") if config["quality"] else "1080p"

    return [
        MissingEpisode(
            season_id=season_id,
            series_id=series["id"],
            series_title=series["title"],
            season=season["season"],
            episode=ep,
            rel_path=season["rel_path"],
            imdb_id=series["imdb_id"],
            quality=quality_pref,
            languages=config["languages"],
            subtitles=config["subtitles"],
            provider=config["provider"],
            servers=config["servers"],
            disabled_servers=config["disabled_servers"],
            working_addons=config["working_addons"],
            experimental_addons_enabled=config["experimental_addons_enabled"],
        )
        for ep in missing
    ]


# ── Stale folder detection (three-tier) ─────────────────────────────────────

def get_folders_needing_inventory_sync() -> list[StaleFolder]:
    """Tier 1: Folders where disk mtime != catalog sync_mtime_ns."""
    stale: list[StaleFolder] = []
    for row in get_seasons_needing_inventory_sync():
        stale.append(StaleFolder(kind="season", id=row["id"], rel_path=row["rel_path"], reason="inventory"))
    # Movies too
    rows = fetchall("SELECT id, rel_path, sync_mtime_ns FROM movies WHERE sync_mtime_ns IS NOT NULL")
    for row in rows:
        stale.append(StaleFolder(kind="movie", id=row["id"], rel_path=row["rel_path"], reason="inventory"))
    return stale


def get_folders_needing_metadata_refresh(now_iso: str | None = None) -> list[StaleFolder]:
    """Tier 2: Folders where metadata_due_at <= now."""
    stale: list[StaleFolder] = []
    for row in get_stale_seasons(now_iso):
        stale.append(StaleFolder(kind="season", id=row["id"], rel_path=row["rel_path"], reason="metadata"))
    for row in get_stale_movies(now_iso):
        stale.append(StaleFolder(kind="movie", id=row["id"], rel_path=row["rel_path"], reason="metadata"))
    return stale


def get_series_needing_new_season_check(current_year: int) -> list[dict]:
    """Tier 3: Series where latest_season < current_year."""
    rows = fetchall(
        "SELECT * FROM series WHERE latest_season < ? AND imdb_id IS NOT NULL",
        (current_year,),
    )
    return [dict(r) for r in rows]


# ── Addon tracking ──────────────────────────────────────────────────────────

def upsert_addon(
    url: str,
    status: str = "untested",
    error: str | None = None,
    download_completed: bool = False,
) -> int:
    """Insert or update addon record. Returns addon_id."""
    now = datetime.now(timezone.utc).isoformat()
    with transaction() as conn:
        row = conn.execute("SELECT id FROM addons WHERE url = ?", (url,)).fetchone()
        if row:
            aid = row["id"]
            if status == "working":
                conn.execute(
                    "UPDATE addons SET status = ?, last_tested_at = ?, last_success_at = ?, downloads_completed = downloads_completed + ? WHERE id = ?",
                    (status, now, now, int(download_completed), aid),
                )
            elif status == "failed":
                conn.execute(
                    "UPDATE addons SET status = ?, last_tested_at = ?, last_error = ? WHERE id = ?",
                    (status, now, error, aid),
                )
            else:
                conn.execute(
                    "UPDATE addons SET status = ?, last_tested_at = ? WHERE id = ?",
                    (status, now, aid),
                )
            return aid
        cursor = conn.execute(
            "INSERT INTO addons (url, status, last_tested_at, last_success_at, last_error, downloads_completed) VALUES (?, ?, ?, ?, ?, ?)",
            (url, status, now, now if status == "working" else None, error, int(download_completed)),
        )
        return cursor.lastrowid


def get_addon_status(url: str) -> str | None:
    """Get addon status."""
    row = fetchone("SELECT status FROM addons WHERE url = ?", (url,))
    return row["status"] if row else None


def get_working_addons(limit: int = 50) -> list[str]:
    """Get URLs of working addons, ordered by success."""
    rows = fetchall(
        "SELECT url FROM addons WHERE status = 'working' ORDER BY downloads_completed DESC, last_success_at DESC LIMIT ?",
        (limit,),
    )
    return [r["url"] for r in rows]


# ── Job runs ────────────────────────────────────────────────────────────────

def record_job_run(job: str, status: str, started_at: str, ended_at: str, skipped_reason: str | None = None, detail: str | None = None) -> int:
    """Record a job run. Returns job_run_id."""
    with transaction() as conn:
        cursor = conn.execute(
            "INSERT INTO job_runs (job, status, started_at, ended_at, skipped_reason, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (job, status, started_at, ended_at, skipped_reason, detail),
        )
        return cursor.lastrowid


def get_recent_job_runs(limit: int = 50) -> list[dict]:
    """Get recent job runs."""
    rows = fetchall(
        "SELECT * FROM job_runs ORDER BY started_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


# ── Settings override (session/runtime) ─────────────────────────────────────

def set_runtime_setting(key: str, value: str) -> None:
    """Set a runtime setting override (e.g., 4K toggle, worker count)."""
    with transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings_override (key, value) VALUES (?, ?)",
            (key, value),
        )


def get_runtime_setting(key: str, default: str | None = None) -> str | None:
    """Get a runtime setting override."""
    row = fetchone("SELECT value FROM settings_override WHERE key = ?", (key,))
    return row["value"] if row else default


def clear_runtime_settings() -> None:
    """Clear all runtime settings (on shutdown)."""
    execute("DELETE FROM settings_override")
