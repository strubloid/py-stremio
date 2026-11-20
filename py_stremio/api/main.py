"""FastAPI dashboard endpoints backed by the shared application services."""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pydantic import SecretStr

from py_stremio.api.progress import progress_hub
from py_stremio.components.configs.app_settings import settings


app = FastAPI(title="py-stremio API", version="0.1.0")
_job_lock = threading.Lock()
_active_jobs: dict[str, dict] = {}
_completed_job_output: dict[tuple[str, str], list[dict]] = {}
_ALLOWED_JOBS = ("configs", "download", "download-quick", "validate-addons", "discover-addons", "calendar-refresh")
_artwork_refresh_lock = threading.Lock()
_artwork_refresh_running = False


class ControlRequest(BaseModel):
    threads: int | None = Field(default=None, ge=1, le=16)
    speed_percent: int | None = Field(default=None, ge=1, le=100)
    allow_4k: bool | None = None


class WatchRequest(BaseModel):
    kind: Literal["season", "movie"]
    episodes: list[int] = Field(min_length=1, max_length=1000)
    watched: bool


class LibraryEnabledRequest(BaseModel):
    enabled: bool


class RedownloadRequest(BaseModel):
    kind: Literal["season", "movie"]
    episode: int | None = Field(default=None, ge=1)


class SettingsUpdate(BaseModel):
    download_threads: int | None = Field(default=None, ge=1, le=16)
    internet_speed_limit: int | None = Field(default=None, ge=1, le=100)
    preferred_languages: list[str] | None = Field(default=None, max_length=15)
    max_download_attempts: int | None = Field(default=None, ge=0, le=50)
    configs_cache_hours: float | None = Field(default=None, ge=0, le=168)
    library_layout: Literal["stremio", "netflix", "apple-tv", "plex", "disney-plus", "prime-video"] | None = None
    real_debrid_api_key: SecretStr | None = None
    premiumize_api_key: SecretStr | None = None
    alldebrid_api_key: SecretStr | None = None
    hdhub_debrid_key: SecretStr | None = None
    torrent_proxy_url: SecretStr | None = None
    clear_secrets: list[Literal["real_debrid", "premiumize", "alldebrid", "hdhub", "torrent_proxy"]] = Field(default_factory=list)


def _authorize(authorization: str | None) -> None:
    token = os.environ.get("PY_STREMIO_API_TOKEN")
    if not token:
        return
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not hmac.compare_digest(supplied, token):
        raise HTTPException(status_code=401, detail="Invalid or missing API token")


def _decode_json(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


@app.on_event("startup")
def initialize_catalog() -> None:
    from py_stremio.storage.db import init_db
    from py_stremio.services.preferences import load_saved_preferences

    init_db()
    load_saved_preferences()


def _refresh_missing_artwork() -> None:
    global _artwork_refresh_running
    try:
        from py_stremio.services.ensure import EnsureFreshService

        EnsureFreshService().run(quiet=True)
    except Exception as exc:
        from py_stremio.components.errors import report_error

        report_error(context="dashboard_artwork_refresh", exception=exc)
    finally:
        with _artwork_refresh_lock:
            _artwork_refresh_running = False


def _schedule_artwork_refresh() -> None:
    global _artwork_refresh_running
    with _artwork_refresh_lock:
        if _artwork_refresh_running:
            return
        _artwork_refresh_running = True
    threading.Thread(target=_refresh_missing_artwork, name="py-stremio-artwork", daemon=True).start()


@app.get("/api/library")
def library(authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    from py_stremio.storage.db import fetchall

    seasons = fetchall(
        """SELECT seasons.*, series.id AS series_id, series.title AS series_title, series.imdb_id AS imdb_id,
                  series.poster_url AS series_poster_url, series.background_url AS background_url
           FROM seasons JOIN series ON series.id = seasons.series_id ORDER BY series.title, seasons.season"""
    )
    movies = fetchall("SELECT * FROM movies ORDER BY title")
    inventory = fetchall(
        """SELECT owner_kind, owner_id,
                  COUNT(DISTINCT CASE WHEN owner_kind='season' THEN episode END) AS episodes,
                  SUM(CASE WHEN owner_kind='movie' THEN 1 ELSE 0 END) AS movies
           FROM files WHERE is_part=0 GROUP BY owner_kind, owner_id"""
    )
    downloaded_by_owner = {
        (row["owner_kind"], row["owner_id"]): row["episodes"] if row["owner_kind"] == "season" else row["movies"]
        for row in inventory
    }
    downloaded_episode_rows = fetchall(
        "SELECT owner_id, episode FROM files WHERE owner_kind='season' AND is_part=0 AND episode IS NOT NULL"
    )
    downloaded_episodes: dict[int, list[int]] = {}
    for row in downloaded_episode_rows:
        downloaded_episodes.setdefault(row["owner_id"], []).append(row["episode"])
    watch_state = fetchall(
        "SELECT owner_kind, owner_id, episode FROM episode_watch_state WHERE watched=1"
    )
    watched_by_owner: dict[tuple[str, int], list[int]] = {}
    for row in watch_state:
        watched_by_owner.setdefault((row["owner_kind"], row["owner_id"]), []).append(row["episode"])
    entries = []
    missing_total = 0
    for row in seasons:
        available = _decode_json(row["available_episodes"], None)
        episode_total = len(available) if available else int(row["episode_count"] or 0)
        downloaded_count = downloaded_by_owner.get(("season", row["id"]), 0)
        missing = max(0, episode_total - downloaded_count)
        missing_total += missing
        entries.append({
            "kind": "season", "id": row["id"], "title": row["series_title"],
            "series_id": row["series_id"],
            "season": row["season"], "imdb_id": row["imdb_id"],
            "poster_url": f"/api/artwork/season/{row['id']}" if row["poster_url"] or row["series_poster_url"] else None,
            "background_url": f"/api/artwork/series/{row['series_id']}?variant=background" if row["background_url"] else None,
            "downloaded": downloaded_count, "total": episode_total,
            "missing": missing, "enabled": bool(row["enabled"]),
            "episode_numbers": available or list(range(1, episode_total + 1)),
            "downloaded_episodes": downloaded_episodes.get(row["id"], []),
            "watched_episodes": watched_by_owner.get(("season", row["id"]), []),
            "metadata_due_at": row["metadata_due_at"], "rel_path": row["rel_path"],
        })
    for row in movies:
        downloaded_count = downloaded_by_owner.get(("movie", row["id"]), 0)
        entries.append({
            "kind": "movie", "id": row["id"], "title": row["title"],
            "imdb_id": row["imdb_id"], "downloaded": downloaded_count,
            "poster_url": f"/api/artwork/movie/{row['id']}" if row["poster_url"] else None,
            "background_url": f"/api/artwork/movie/{row['id']}?variant=background" if row["background_url"] else None,
            "release_date": row["release_date"],
            "total": 1, "missing": max(0, 1 - downloaded_count),
            "watched": 0 in watched_by_owner.get(("movie", row["id"]), []),
            "enabled": bool(row["enabled"]), "metadata_due_at": row["metadata_due_at"],
            "rel_path": row["rel_path"],
        })
        missing_total += entries[-1]["missing"]
    if any(not entry.get("poster_url") or (entry["kind"] == "movie" and not entry.get("release_date")) for entry in entries):
        _schedule_artwork_refresh()
    return {"entries": entries, "series_seasons": len(seasons), "movies": len(movies), "missing": missing_total}


@app.put("/api/library/{kind}/{item_id}/enabled")
def set_library_item_enabled(
    kind: Literal["season", "movie"],
    item_id: int,
    request: LibraryEnabledRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(authorization)
    from py_stremio.components.library.library_scanner import FolderType, ScannedFolder
    from py_stremio.storage.db import fetchone

    table = "seasons" if kind == "season" else "movies"
    row = fetchone(f"SELECT rel_path FROM {table} WHERE id=?", (item_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Library item not found")
    from py_stremio.components.configs.config_file import load_config, save_config

    config, config_path = load_config(settings.ROOT_FOLDER / row["rel_path"])
    config.enabled = request.enabled
    save_config(config_path, config)
    from py_stremio.services.library_catalog import sync_catalog_from_folders
    from py_stremio.utils.media import parse_season_from_folder

    folder_path = config_path.parent
    folder_type = FolderType.SERIES if kind == "season" else FolderType.MOVIES
    sync_catalog_from_folders([
        ScannedFolder(
            path=folder_path,
            folder_type=folder_type,
            parent_folder=folder_path.parent,
            season_number=parse_season_from_folder(folder_path.name) if kind == "season" else None,
        )
    ], remove_missing=False)
    return {"kind": kind, "id": item_id, "enabled": request.enabled}


@app.delete("/api/library/{kind}/{item_id}")
def remove_library_item(
    kind: Literal["series", "season", "movie"],
    item_id: int,
    authorization: str | None = Header(default=None),
) -> dict:
    """Remove a library item and its tracking data; season removal deletes its folder."""
    _authorize(authorization)
    from py_stremio.storage.db import fetchone, transaction

    if kind == "season":
        with _job_lock:
            if any(name in _active_jobs for name in ("download", "download-quick", "configs")):
                raise HTTPException(status_code=409, detail="Wait for the active library or download job before removing a season")
        season = fetchone("SELECT id, series_id, rel_path FROM seasons WHERE id=?", (item_id,))
        if not season:
            raise HTTPException(status_code=404, detail="Season not found")
        root = settings.ROOT_FOLDER.resolve()
        folder_path = root / season["rel_path"]
        resolved_path = folder_path.resolve()
        if resolved_path == root or not resolved_path.is_relative_to(root) or folder_path.is_symlink():
            raise HTTPException(status_code=400, detail="Season folder is outside the configured media root")
        if folder_path.exists() and not folder_path.is_dir():
            raise HTTPException(status_code=409, detail="Season path is not a directory")
        if folder_path.exists():
            try:
                shutil.rmtree(folder_path)
            except OSError as exc:
                raise HTTPException(status_code=500, detail="Could not delete the season folder") from exc

        with transaction() as conn:
            for table in ("files", "attempts", "episode_watch_state", "owner_state"):
                conn.execute(f"DELETE FROM {table} WHERE owner_kind='season' AND owner_id=?", (item_id,))
            conn.execute("DELETE FROM seasons WHERE id=?", (item_id,))
            if not conn.execute("SELECT 1 FROM seasons WHERE series_id=? LIMIT 1", (season["series_id"],)).fetchone():
                conn.execute("DELETE FROM calendar_episodes WHERE series_id=?", (season["series_id"],))
                conn.execute("DELETE FROM calendar_sync WHERE series_id=?", (season["series_id"],))
                conn.execute("DELETE FROM series WHERE id=?", (season["series_id"],))
        return {"removed": True, "kind": kind, "id": item_id, "folder_deleted": True}

    with transaction() as conn:
        if kind == "series":
            season_rows = conn.execute("SELECT id FROM seasons WHERE series_id = ?", (item_id,)).fetchall()
            if not conn.execute("SELECT 1 FROM series WHERE id = ?", (item_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Series not found")
            season_ids = [row["id"] for row in season_rows]
            for season_id in season_ids:
                for table in ("files", "attempts", "episode_watch_state", "owner_state"):
                    conn.execute(f"DELETE FROM {table} WHERE owner_kind = 'season' AND owner_id = ?", (season_id,))
            conn.execute("DELETE FROM calendar_episodes WHERE series_id = ?", (item_id,))
            conn.execute("DELETE FROM calendar_sync WHERE series_id = ?", (item_id,))
            conn.execute("DELETE FROM seasons WHERE series_id = ?", (item_id,))
            conn.execute("DELETE FROM series WHERE id = ?", (item_id,))
        else:
            if not conn.execute("SELECT 1 FROM movies WHERE id = ?", (item_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Movie not found")
            for table in ("files", "attempts", "episode_watch_state", "owner_state"):
                conn.execute(f"DELETE FROM {table} WHERE owner_kind = 'movie' AND owner_id = ?", (item_id,))
            conn.execute("DELETE FROM movies WHERE id = ?", (item_id,))
    return {"removed": True, "kind": kind, "id": item_id}


@app.get("/api/jobs")
def jobs(authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    from py_stremio.storage.catalog import get_recent_job_runs
    from py_stremio.services.job_log import read_job_runs

    with _job_lock:
        active = [
            {**job, "progress": list(job.get("progress", {}).values())}
            for job in _active_jobs.values()
        ]
    history = get_recent_job_runs()
    known = {(row["job"], row["started_at"]) for row in history}
    for record in read_job_runs(limit=100):
        key = (record.get("job"), record.get("started_at"))
        if key in known:
            continue
        record["id"] = f"{key[0]}:{key[1]}"
        record["detail"] = record.get("error")
        history.append(record)
    with _job_lock:
        for record in history:
            record["output"] = _completed_job_output.get(
                (record.get("job", ""), record.get("started_at", "")), []
            )
    from py_stremio.components.errors.error_reporter import redact_url

    for record in history:
        if record.get("detail"):
            record["detail"] = redact_url(record["detail"])
        if record.get("error"):
            record["error"] = redact_url(record["error"])
    history.sort(key=lambda row: row.get("started_at", ""), reverse=True)
    return {"active": active, "history": history[:100]}


@app.get("/api/episodes/{owner_id}")
def episode_history(
    owner_id: int,
    kind: str = "season",
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(authorization)
    if kind not in ("season", "movie"):
        raise HTTPException(status_code=400, detail="kind must be season or movie")
    from py_stremio.storage.db import fetchall

    files = fetchall(
        "SELECT rel_path, episode, size, mtime_ns, is_part FROM files WHERE owner_kind=? AND owner_id=? ORDER BY episode, rel_path",
        (kind, owner_id),
    )
    attempts = fetchall(
        "SELECT episode, started_at, completed_at, success, server_url, error, bytes, quality FROM attempts WHERE owner_kind=? AND owner_id=? ORDER BY started_at DESC",
        (kind, owner_id),
    )
    watched_rows = fetchall(
        "SELECT episode FROM episode_watch_state WHERE owner_kind=? AND owner_id=? AND watched=1",
        (kind, owner_id),
    )
    from py_stremio.components.errors.error_reporter import redact_url

    safe_attempts = []
    for row in attempts:
        attempt = dict(row)
        attempt["server_url"] = redact_url(attempt["server_url"])
        attempt["error"] = redact_url(attempt["error"])
        safe_attempts.append(attempt)
    return {
        "files": [dict(row) for row in files],
        "attempts": safe_attempts,
        "watched_episodes": [row["episode"] for row in watched_rows],
    }


@app.put("/api/episodes/{owner_id}/watch")
def set_watched(
    owner_id: int,
    request: WatchRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(authorization)
    from py_stremio.storage.db import fetchone, transaction

    if request.kind == "season":
        owner = fetchone("SELECT episode_count, available_episodes FROM seasons WHERE id=?", (owner_id,))
        if owner is None:
            raise HTTPException(status_code=404, detail="Season not found")
        available = _decode_json(owner["available_episodes"], None)
        known = set(available or range(1, int(owner["episode_count"] or 0) + 1))
        if any(episode not in known for episode in request.episodes):
            raise HTTPException(status_code=422, detail="Episode is outside this season")
    else:
        if fetchone("SELECT id FROM movies WHERE id=?", (owner_id,)) is None:
            raise HTTPException(status_code=404, detail="Movie not found")
        if request.episodes != [0]:
            raise HTTPException(status_code=422, detail="Movies use episode 0 for watch state")

    now = datetime.now(timezone.utc).isoformat()
    with transaction() as conn:
        if request.watched:
            conn.executemany(
                """INSERT OR REPLACE INTO episode_watch_state
                   (owner_kind, owner_id, episode, watched, updated_at) VALUES (?, ?, ?, 1, ?)""",
                [(request.kind, owner_id, episode, now) for episode in request.episodes],
            )
        else:
            conn.executemany(
                "DELETE FROM episode_watch_state WHERE owner_kind=? AND owner_id=? AND episode=?",
                [(request.kind, owner_id, episode) for episode in request.episodes],
            )
    return {"owner_id": owner_id, "kind": request.kind, "episodes": request.episodes, "watched": request.watched}


def _run_redownload(owner_id: int, kind: str, episode: int | None, job_key: str) -> None:
    from py_stremio.storage.catalog import record_job_run
    from py_stremio.storage.db import fetchall, fetchone

    started = datetime.now(timezone.utc).isoformat()
    status = "failed"
    detail = None
    backups: list[tuple[Path, Path]] = []
    root = settings.ROOT_FOLDER.resolve()
    with _job_lock:
        _active_jobs[job_key] = {
            "job": "redownload", "status": "running", "started_at": started,
            "owner_id": owner_id, "kind": kind, "episode": episode,
        }
    try:
        if kind == "season":
            row = fetchone("SELECT rel_path FROM seasons WHERE id=?", (owner_id,))
            if row is None:
                raise ValueError("Season not found")
            folder = (root / row["rel_path"]).resolve()
            targets = fetchall(
                "SELECT rel_path FROM files WHERE owner_kind='season' AND owner_id=? AND episode=? AND is_part=0",
                (owner_id, episode),
            )
        else:
            row = fetchone("SELECT rel_path FROM movies WHERE id=?", (owner_id,))
            if row is None:
                raise ValueError("Movie not found")
            folder = (root / row["rel_path"]).resolve()
            targets = fetchall(
                "SELECT rel_path FROM files WHERE owner_kind='movie' AND owner_id=? AND is_part=0",
                (owner_id,),
            )
        if not folder.is_relative_to(root):
            raise ValueError("Media path is outside the configured root")
        for target in targets:
            original = (folder / target["rel_path"]).resolve()
            if original.parent != folder or not original.is_file():
                continue
            backup = folder / f".py-stremio-redownload-{uuid4().hex}.backup"
            shutil.move(original, backup)
            backups.append((original, backup))

        if kind == "season":
            from py_stremio.components.download.processing import process_season_folder

            result = process_season_folder(folder, max_workers=1, quiet_output=True, force_episode=episode)
        else:
            from py_stremio.components.download.processing import process_movie_folder

            result = process_movie_folder(folder, force_redownload=True)
        if result.get("downloaded", 0):
            status = "ok"
            for _original, backup in backups:
                backup.unlink(missing_ok=True)
        else:
            from py_stremio.components.errors.error_reporter import redact_url

            detail = redact_url(result.get("error") or "No replacement download completed; restored the previous file.")
            for original, backup in backups:
                if backup.exists():
                    shutil.move(backup, original)
        from py_stremio.services.ensure import EnsureFreshService

        EnsureFreshService().run(quiet=True)
    except Exception as exc:
        from py_stremio.components.errors.error_reporter import redact_url

        detail = redact_url(str(exc))
        for original, backup in backups:
            if backup.exists() and not original.exists():
                shutil.move(backup, original)
    finally:
        ended = datetime.now(timezone.utc).isoformat()
        try:
            record_job_run("redownload", status, started, ended, detail=detail)
        finally:
            with _job_lock:
                _active_jobs.pop(job_key, None)


@app.post("/api/episodes/{owner_id}/redownload", status_code=202)
def redownload_episode(
    owner_id: int,
    request: RedownloadRequest,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(authorization)
    from py_stremio.storage.db import fetchone

    if request.kind == "season" and request.episode is None:
        raise HTTPException(status_code=422, detail="A season episode number is required")
    if request.kind == "season":
        season = fetchone("SELECT episode_count, available_episodes FROM seasons WHERE id=?", (owner_id,))
        if season is None:
            raise HTTPException(status_code=404, detail="Season not found")
        known = set(_decode_json(season["available_episodes"], None) or range(1, int(season["episode_count"] or 0) + 1))
        if request.episode not in known:
            raise HTTPException(status_code=422, detail="Episode is outside this season")
    elif request.episode is not None:
        raise HTTPException(status_code=422, detail="Movies do not have episode numbers")
    elif fetchone("SELECT id FROM movies WHERE id=?", (owner_id,)) is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    job_key = f"redownload:{request.kind}:{owner_id}:{request.episode or 0}"
    with _job_lock:
        if any(key in _active_jobs for key in ("download", "download-quick")) or any(key.startswith("redownload:") for key in _active_jobs):
            raise HTTPException(status_code=409, detail="A download job is already running")
        if job_key in _active_jobs:
            raise HTTPException(status_code=409, detail="This item is already being re-downloaded")
        _active_jobs[job_key] = {"job": "redownload", "status": "queued", "started_at": datetime.now(timezone.utc).isoformat()}
    background_tasks.add_task(_run_redownload, owner_id, request.kind, request.episode, job_key)
    return {"job": "redownload", "status": "queued", "owner_id": owner_id, "episode": request.episode}


@app.get("/api/addons")
def addons(authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    from py_stremio.storage.db import fetchall

    from py_stremio.components.errors.error_reporter import redact_url

    items = []
    for row in fetchall("SELECT * FROM addons ORDER BY downloads_completed DESC, url"):
        item = dict(row)
        item["url"] = redact_url(item["url"])
        item["last_error"] = redact_url(item["last_error"])
        items.append(item)
    return {"addons": items}


@app.get("/api/calendar")
def calendar(
    year: int = Query(ge=1900, le=2200),
    month: int = Query(ge=1, le=12),
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(authorization)
    from py_stremio.services.calendar import get_calendar_month

    data = get_calendar_month(year, month)
    for event in data["events"]:
        if event.get("thumbnail_url"):
            event["image_url"] = f"/api/artwork/calendar/{event['id']}?variant=thumbnail"
        elif event.get("poster_url"):
            event["image_url"] = f"/api/artwork/series/{event['series_id']}"
        else:
            event["image_url"] = None
    if data["needs_refresh"]:
        _schedule_calendar_refresh()
    return data


@app.get("/api/spotlight")
def spotlight(
    days: int = Query(default=14, ge=1, le=90),
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(authorization)
    from py_stremio.services.calendar import get_calendar_month
    from py_stremio.storage.db import fetchall

    now = datetime.now(timezone.utc)
    cutoff = (now.date() - timedelta(days=days)).isoformat()
    today = now.date().isoformat()
    calendar_cache = get_calendar_month(now.year, now.month)
    if calendar_cache["needs_refresh"]:
        _schedule_calendar_refresh()

    recent_episodes = fetchall(
        """SELECT series.id AS series_id, series.title, series.poster_url, series.background_url,
                  calendar_episodes.id AS calendar_episode_id, calendar_episodes.season,
                  calendar_episodes.episode, calendar_episodes.title AS episode_title,
                  calendar_episodes.release_at, calendar_episodes.thumbnail_url
           FROM calendar_episodes JOIN series ON series.id=calendar_episodes.series_id
           WHERE substr(calendar_episodes.release_at, 1, 10)>=?
             AND substr(calendar_episodes.release_at, 1, 10)<=?
           ORDER BY calendar_episodes.release_at DESC""",
        (cutoff, today),
    )
    items = []
    seen_series: set[int] = set()
    for row in recent_episodes:
        if row["series_id"] in seen_series:
            continue
        seen_series.add(row["series_id"])
        items.append({
            "kind": "series",
            "id": row["series_id"],
            "series_id": row["series_id"],
            "title": row["title"],
            "poster_url": f"/api/artwork/series/{row['series_id']}" if row["poster_url"] else None,
            "background_url": f"/api/artwork/series/{row['series_id']}?variant=background" if row["background_url"] else None,
            "episode_image_url": f"/api/artwork/calendar/{row['calendar_episode_id']}?variant=thumbnail" if row["thumbnail_url"] else None,
            "season": row["season"],
            "episode": row["episode"],
            "episode_title": row["episode_title"],
            "release_at": row["release_at"],
        })

    recent_movies = fetchall(
        """SELECT id, title, release_date, poster_url, background_url FROM movies
           WHERE release_date>=? AND release_date<=? ORDER BY release_date DESC, title""",
        (cutoff, today),
    )
    items.extend({
        "kind": "movie",
        "id": row["id"],
        "title": row["title"],
        "poster_url": f"/api/artwork/movie/{row['id']}" if row["poster_url"] else None,
        "background_url": f"/api/artwork/movie/{row['id']}?variant=background" if row["background_url"] else None,
        "release_at": row["release_date"],
    } for row in recent_movies)
    items.sort(key=lambda item: item["release_at"], reverse=True)
    return {"days": days, "items": items, "refreshed_at": calendar_cache["last_refreshed"]}


@app.get("/api/artwork/{kind}/{owner_id}", include_in_schema=False)
def artwork(
    kind: Literal["series", "season", "movie", "calendar"],
    owner_id: int,
    variant: Literal["poster", "background", "thumbnail"] = "poster",
) -> FileResponse:
    from py_stremio.api.artwork_cache import get_cached_artwork
    from py_stremio.storage.db import fetchone

    if kind == "series":
        field = "background_url" if variant == "background" else "poster_url"
        row = fetchone(f"SELECT {field} AS image_url FROM series WHERE id=?", (owner_id,))
    elif kind == "season":
        row = fetchone(
            """SELECT COALESCE(seasons.poster_url, series.poster_url) AS image_url
               FROM seasons JOIN series ON series.id=seasons.series_id WHERE seasons.id=?""",
            (owner_id,),
        )
    elif kind == "movie":
        field = "background_url" if variant == "background" else "poster_url"
        row = fetchone(f"SELECT {field} AS image_url FROM movies WHERE id=?", (owner_id,))
    else:
        field = "thumbnail_url" if variant == "thumbnail" else "NULL"
        row = fetchone(f"SELECT {field} AS image_url FROM calendar_episodes WHERE id=?", (owner_id,))
    if not row or not row["image_url"]:
        raise HTTPException(status_code=404, detail="Artwork is not available")
    try:
        cached = get_cached_artwork(row["image_url"])
    except Exception as exc:
        from py_stremio.components.errors import report_error

        report_error(context="load_artwork", exception=exc, url=row["image_url"])
        raise HTTPException(status_code=502, detail="Artwork could not be loaded") from exc
    return FileResponse(cached.path, media_type=cached.media_type, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/settings")
def get_settings(authorization: str | None = Header(default=None)) -> dict:
    _authorize(authorization)
    from py_stremio.services.preferences import get_preferences

    return get_preferences()


@app.put("/api/settings")
def update_settings(
    request: SettingsUpdate,
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(authorization)
    from py_stremio.services.preferences import save_preferences, save_service_secrets

    payload = request.model_dump(exclude_none=True)
    secret_names = {
        "real_debrid_api_key": "real_debrid",
        "premiumize_api_key": "premiumize",
        "alldebrid_api_key": "alldebrid",
        "hdhub_debrid_key": "hdhub",
        "torrent_proxy_url": "torrent_proxy",
    }
    secrets = {}
    for field_name, preference_name in secret_names.items():
        secret = payload.pop(field_name, None)
        if secret is not None:
            secrets[preference_name] = secret.get_secret_value()
    clear_secrets = payload.pop("clear_secrets", [])
    preferences = save_preferences(payload)
    if secrets or clear_secrets:
        preferences = save_service_secrets(secrets, clear_secrets)
    return preferences


@app.get("/api/controls")
def get_controls(authorization: str | None = Header(default=None)) -> dict | None:
    _authorize(authorization)
    from py_stremio.services.session_controls import apply_session_controls

    current = apply_session_controls()
    if current is None:
        return None
    return current


@app.post("/api/controls")
def update_controls(
    controls: ControlRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(authorization)
    from py_stremio.services.session_controls import apply_session_controls

    current = apply_session_controls(
        workers=controls.threads,
        speed_percent=controls.speed_percent,
        allow_4k=controls.allow_4k,
    )
    if current is None:
        raise HTTPException(status_code=409, detail="No download session is active")
    return current


def _publish_job_output(name: str, message: str, item: dict | None = None) -> None:
    status = "failed" if message.startswith("✗") else (
        "running" if message.startswith(("Starting", "Scanning", "Checking", "Refreshing", "Found")) else "complete"
    )
    line = {"message": message, "timestamp": datetime.now(timezone.utc).isoformat(), "status": status}
    if item:
        line["item"] = item
    with _job_lock:
        job = _active_jobs.get(name)
        if job is not None:
            job.setdefault("output", []).append(line)
    progress_hub.publish({"type": "job_output", "job": name, **line})


def _store_download_progress(name: str, event: dict) -> None:
    title = str(event.get("title") or "Download")
    season = event.get("season")
    episode = event.get("episode")
    key = (title, season, episode)
    with _job_lock:
        job = _active_jobs.get(name)
        if job is not None:
            job.setdefault("progress", {})[key] = {
                **event,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }


def _run_job(name: str) -> None:
    from py_stremio.storage.catalog import record_job_run

    started = datetime.now(timezone.utc).isoformat()
    with _job_lock:
        job = _active_jobs.setdefault(name, {"job": name, "output": []})
        job.update({"job": name, "status": "running", "started_at": started})
        job.setdefault("progress", {})
    status = "ok"
    detail = None
    try:
        from py_stremio.app import AppService

        service = AppService()
        _publish_job_output(name, f"Starting {name.replace('-', ' ')} job")
        if name == "configs":
            _publish_job_output(name, "Scanning folders and checking for new seasons")
            folders = service.scanner.run(progress_callback=lambda message: _publish_job_output(name, message))
            _publish_job_output(name, f"Found {len(folders)} managed folder(s); refreshing metadata")
            updated = service.metadata.run(
                folders=folders,
                quiet=True,
                progress_callback=lambda message: _publish_job_output(name, message),
                item_callback=lambda item: _publish_job_output(
                    name,
                    f"{item['status']}: {item['title']} {item['season']}",
                    item=item,
                ),
            )
            service.scanner.sync_catalog(
                folders,
                progress_callback=lambda message: _publish_job_output(name, message),
            )
            _publish_job_output(name, f"Library update complete ({updated} metadata record(s) updated)")
        elif name == "download":
            _publish_job_output(name, "Scanning folders and checking for new seasons")
            folders = service.scanner.run(progress_callback=lambda message: _publish_job_output(name, message))
            _publish_job_output(name, f"Found {len(folders)} managed folder(s); refreshing metadata")
            service.metadata.run(
                folders=folders,
                quiet=True,
                progress_callback=lambda message: _publish_job_output(name, message),
                item_callback=lambda item: _publish_job_output(
                    name,
                    f"{item['status']}: {item['title']} {item['season']}",
                    item=item,
                ),
            )
            service.scanner.sync_catalog(
                folders,
                progress_callback=lambda message: _publish_job_output(name, message),
            )
            _publish_job_output(name, "Validating addon URLs")
            from py_stremio.components.addons.addon_validator import validate_and_update

            validate_and_update()
            _publish_job_output(name, f"Starting downloads for {len(folders)} managed folder(s)")
            from py_stremio.components.reports.output_writer import suppress_all_output

            with suppress_all_output():
                service.downloader.run(
                    folders=folders,
                    quiet=True,
                    max_workers=settings.DOWNLOAD_THREADS,
                    progress_callback=lambda event: _store_download_progress(name, event),
                    terminal_output=False,
                )
        elif name == "download-quick":
            _publish_job_output(name, "Scanning existing library folders before download")
            from py_stremio.components.reports.output_writer import suppress_all_output

            with suppress_all_output():
                service.downloader.run(
                    quiet=True,
                    max_workers=settings.DOWNLOAD_THREADS,
                    progress_callback=lambda event: _store_download_progress(name, event),
                    terminal_output=False,
                )
        elif name == "validate-addons":
            from py_stremio.components.addons.addon_validator import validate_and_update

            validate_and_update()
        elif name == "calendar-refresh":
            from py_stremio.services.calendar import refresh_calendar

            result = refresh_calendar(force=True)
            if result["failed"]:
                status = "failed"
                detail = f"Calendar refreshed for {result['updated']} series; {result['failed']} failed."
        else:
            from py_stremio.components.collect import discover_new_addons

            discover_new_addons()
    except Exception as exc:
        status = "failed"
        from py_stremio.components.errors.error_reporter import redact_url

        detail = redact_url(str(exc))
        _publish_job_output(name, f"✗ Job failed: {detail}")
    finally:
        if status == "ok":
            _publish_job_output(name, "✓ Job completed")
        ended = datetime.now(timezone.utc).isoformat()
        try:
            record_job_run(name, status, started, ended, detail=detail)
        finally:
            with _job_lock:
                output = _active_jobs.get(name, {}).get("output", [])
                _completed_job_output[(name, started)] = list(output)
                if len(_completed_job_output) > 50:
                    oldest = next(iter(_completed_job_output))
                    _completed_job_output.pop(oldest, None)
                _active_jobs.pop(name, None)


def _schedule_calendar_refresh() -> None:
    with _job_lock:
        if "calendar-refresh" in _active_jobs:
            return
        _active_jobs["calendar-refresh"] = {
            "job": "calendar-refresh",
            "status": "queued",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
    threading.Thread(target=_run_job, args=("calendar-refresh",), name="py-stremio-calendar", daemon=True).start()


@app.post("/api/jobs/{name}", status_code=202)
def start_job(
    name: str,
    background_tasks: BackgroundTasks,
    authorization: str | None = Header(default=None),
) -> dict:
    _authorize(authorization)
    if name not in _ALLOWED_JOBS:
        raise HTTPException(status_code=404, detail="Unknown job")
    with _job_lock:
        redownload_active = any(key.startswith("redownload:") for key in _active_jobs)
        download_active = any(key in _active_jobs for key in ("download", "download-quick"))
        if name in _active_jobs or (name in ("download", "download-quick") and (redownload_active or download_active)):
            raise HTTPException(status_code=409, detail="Job is already running")
        _active_jobs[name] = {
            "job": name,
            "status": "queued",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "output": [],
            "progress": {},
        }
    background_tasks.add_task(_run_job, name)
    return {"job": name, "status": "queued"}


@app.websocket("/api/progress")
async def progress(websocket: WebSocket) -> None:
    token = os.environ.get("PY_STREMIO_API_TOKEN")
    if token and not hmac.compare_digest(websocket.query_params.get("token", ""), token):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    async for queue in progress_hub.subscribe():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=20)
                await websocket.send_json(event)
        except asyncio.TimeoutError:
            await websocket.send_json({"type": "keepalive"})
        except WebSocketDisconnect:
            return


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    index = Path(__file__).resolve().parent / "static" / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Dashboard assets are not built. Run npm run build in ui/react.")
    return FileResponse(index)


@app.get("/libray", include_in_schema=False)
@app.get("/library", include_in_schema=False)
def library_dashboard() -> FileResponse:
    return dashboard()


assets = Path(__file__).resolve().parent / "static" / "assets"
if assets.exists():
    app.mount("/assets", StaticFiles(directory=assets), name="assets")
