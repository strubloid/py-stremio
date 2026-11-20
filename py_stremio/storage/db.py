"""Database connection, schema, and migrations for the py-stremio catalog."""
from __future__ import annotations
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from py_stremio.components.configs.app_settings import settings


SCHEMA_VERSION = 7

SCHEMA_SQL = """
-- catalog metadata / schema version
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE series (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    imdb_id       TEXT,
    poster_url    TEXT,
    background_url TEXT,
    rel_path      TEXT NOT NULL,
    latest_season INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(rel_path)
);

CREATE TABLE seasons (
    id                           INTEGER PRIMARY KEY,
    series_id                    INTEGER NOT NULL REFERENCES series(id),
    season                       INTEGER NOT NULL,
    rel_path                     TEXT NOT NULL,
    poster_url                   TEXT,
    episode_count                INTEGER,
    available_episodes           TEXT,
    current_episode_download     INTEGER DEFAULT 1,
    enabled                      INTEGER DEFAULT 1,
    watched                      INTEGER NOT NULL DEFAULT 0,
    quality                      TEXT,
    languages                    TEXT,
    subtitles                    TEXT,
    provider                     TEXT,
    search_group                 TEXT,
    download_all_related         INTEGER DEFAULT 1,
    servers                      TEXT,
    disabled_servers             TEXT,
    working_addons               TEXT,
    experimental_addons_enabled  INTEGER DEFAULT 1,
    metadata_last_checked        TEXT,
    metadata_due_at              TEXT,
    sync_mtime_ns                INTEGER,
    last_inventoried_at          TEXT,
    updated_at                   TEXT,
    UNIQUE(series_id, season)
);

CREATE TABLE movies (
    id                     INTEGER PRIMARY KEY,
    title                  TEXT NOT NULL,
    imdb_id                TEXT,
    poster_url             TEXT,
    background_url         TEXT,
    release_date           TEXT,
    rel_path               TEXT NOT NULL,
    enabled                INTEGER DEFAULT 1,
    quality                TEXT,
    languages              TEXT,
    subtitles              TEXT,
    provider               TEXT,
    search_group           TEXT,
    servers                TEXT,
    disabled_servers       TEXT,
    working_addons         TEXT,
    metadata_last_checked  TEXT,
    metadata_due_at        TEXT,
    sync_mtime_ns          INTEGER,
    last_inventoried_at    TEXT,
    UNIQUE(rel_path)
);

CREATE TABLE files (
    id         INTEGER PRIMARY KEY,
    owner_kind TEXT NOT NULL,
    owner_id   INTEGER NOT NULL,
    rel_path   TEXT NOT NULL,
    episode    INTEGER,
    size       INTEGER,
    mtime_ns   INTEGER,
    is_part    INTEGER DEFAULT 0,
    UNIQUE(owner_kind, owner_id, rel_path)
);

CREATE TABLE attempts (
    id              INTEGER PRIMARY KEY,
    owner_kind      TEXT NOT NULL,
    owner_id        INTEGER NOT NULL,
    episode         INTEGER,
    started_at      TEXT,
    completed_at    TEXT,
    success         INTEGER,
    server_url      TEXT,
    error           TEXT,
    bytes           INTEGER,
    quality         TEXT
);

CREATE TABLE addons (
    id                   INTEGER PRIMARY KEY,
    url                  TEXT UNIQUE NOT NULL,
    status               TEXT DEFAULT 'unknown',
    last_tested_at       TEXT,
    last_success_at      TEXT,
    last_error           TEXT,
    downloads_completed  INTEGER DEFAULT 0
);

CREATE TABLE job_runs (
    id           INTEGER PRIMARY KEY,
    job          TEXT NOT NULL,
    started_at   TEXT,
    ended_at     TEXT,
    status       TEXT,
    skipped_reason TEXT,
    detail       TEXT
);

CREATE TABLE settings_override (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE owner_state (
    owner_kind TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    state_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(owner_kind, owner_id)
);

CREATE TABLE episode_watch_state (
    owner_kind TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    watched INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(owner_kind, owner_id, episode)
);

CREATE TABLE calendar_sync (
    series_id INTEGER PRIMARY KEY REFERENCES series(id),
    refreshed_at TEXT NOT NULL
);

CREATE TABLE calendar_episodes (
    id INTEGER PRIMARY KEY,
    series_id INTEGER NOT NULL REFERENCES series(id),
    season INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    title TEXT,
    overview TEXT,
    release_at TEXT NOT NULL,
    thumbnail_url TEXT,
    UNIQUE(series_id, season, episode)
);

-- Indexes for common queries
CREATE INDEX idx_seasons_series_id ON seasons(series_id);
CREATE INDEX idx_seasons_metadata_due_at ON seasons(metadata_due_at);
CREATE INDEX idx_files_owner ON files(owner_kind, owner_id, episode);
CREATE INDEX idx_series_imdb_id ON series(imdb_id);
CREATE INDEX idx_movies_metadata_due_at ON movies(metadata_due_at);
CREATE INDEX idx_movies_release_date ON movies(release_date);
CREATE INDEX idx_calendar_release_at ON calendar_episodes(release_at);
CREATE INDEX idx_attempts_owner ON attempts(owner_kind, owner_id, episode);
CREATE INDEX idx_job_runs_job_started ON job_runs(job, started_at);
"""

# Thread-local storage for connections
_local = threading.local()


def get_db_path() -> Path:
    """Resolve the database path from env or default location."""
    env_path = os.environ.get("PY_STREMIO_DB")
    if env_path:
        return Path(env_path).expanduser()
    # Default: ~/.local/share/py-stremio/library.sqlite
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "py-stremio" / "library.sqlite"


def _configure_connection(conn: sqlite3.Connection) -> None:
    """Apply PRAGMA settings for WAL mode and performance."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row


def get_connection() -> sqlite3.Connection:
    """Get a thread-local database connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        db_path = get_db_path()
        db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            descriptor = os.open(db_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass
        _configure_connection(conn)
        _local.conn = conn
    return _local.conn


def close_connection() -> None:
    """Close the thread-local connection."""
    if hasattr(_local, "conn") and _local.conn is not None:
        _local.conn.close()
        _local.conn = None


@contextmanager
def transaction():
    """Context manager for a database transaction."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    """Initialize the database schema if not present."""
    conn = get_connection()
    cursor = conn.cursor()

    # Check if meta table exists (schema already initialized)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta'")
    if not cursor.fetchone():
        # Fresh install - create all tables
        conn.executescript(SCHEMA_SQL)
        cursor.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        cursor.execute("INSERT INTO meta (key, value) VALUES ('media_root', ?)", (str(settings.ROOT_FOLDER),))
        conn.commit()
        return

    # Check current schema version
    cursor.execute("SELECT value FROM meta WHERE key = 'schema_version'")
    row = cursor.fetchone()
    current_version = int(row["value"]) if row else 0

    if current_version == 0:
        # Meta table exists but no version - treat as fresh
        conn.executescript(SCHEMA_SQL)
        cursor.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        cursor.execute("INSERT INTO meta (key, value) VALUES ('media_root', ?)", (str(settings.ROOT_FOLDER),))
        conn.commit()
    elif current_version < SCHEMA_VERSION:
        # Run migrations (placeholder for future versions)
        _run_migrations(conn, current_version, SCHEMA_VERSION)
    else:
        # Verify media_root matches
        cursor.execute("SELECT value FROM meta WHERE key = 'media_root'")
        row = cursor.fetchone()
        if row and row["value"] != str(settings.ROOT_FOLDER):
            # Media root changed - could trigger a re-sync
            pass


def _run_migrations(conn: sqlite3.Connection, from_version: int, to_version: int) -> None:
    """Run schema migrations between versions."""
    cursor = conn.cursor()
    if from_version < 2 <= to_version:
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS owner_state (
                owner_kind TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(owner_kind, owner_id)
            )"""
        )
    if from_version < 3 <= to_version:
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS episode_watch_state (
                owner_kind TEXT NOT NULL,
                owner_id INTEGER NOT NULL,
                episode INTEGER NOT NULL,
                watched INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(owner_kind, owner_id, episode)
            )"""
        )
    if from_version < 4 <= to_version:
        conn.execute("ALTER TABLE series ADD COLUMN poster_url TEXT")
        conn.execute("ALTER TABLE series ADD COLUMN background_url TEXT")
        conn.execute("ALTER TABLE seasons ADD COLUMN poster_url TEXT")
        conn.execute("ALTER TABLE movies ADD COLUMN poster_url TEXT")
        conn.execute("ALTER TABLE movies ADD COLUMN background_url TEXT")
        due_at = datetime.now(timezone.utc).isoformat()
        conn.execute("UPDATE seasons SET metadata_due_at=? WHERE poster_url IS NULL", (due_at,))
        conn.execute("UPDATE movies SET metadata_due_at=? WHERE poster_url IS NULL", (due_at,))
    if from_version < 5 <= to_version:
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS calendar_sync (
                series_id INTEGER PRIMARY KEY REFERENCES series(id),
                refreshed_at TEXT NOT NULL
            )"""
        )
    if from_version < 6 <= to_version:
        cursor.execute("ALTER TABLE movies ADD COLUMN release_date TEXT")
        cursor.execute(
            "UPDATE movies SET metadata_due_at=? WHERE release_date IS NULL",
            (datetime.now(timezone.utc).isoformat(),),
        )
    if from_version < 7 <= to_version:
        cursor.execute("ALTER TABLE seasons ADD COLUMN watched INTEGER NOT NULL DEFAULT 0")
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS calendar_episodes (
                id INTEGER PRIMARY KEY,
                series_id INTEGER NOT NULL REFERENCES series(id),
                season INTEGER NOT NULL,
                episode INTEGER NOT NULL,
                title TEXT,
                overview TEXT,
                release_at TEXT NOT NULL,
                thumbnail_url TEXT,
                UNIQUE(series_id, season, episode)
            )"""
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_movies_release_date ON movies(release_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_calendar_release_at ON calendar_episodes(release_at)")
    cursor.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(to_version),))
    conn.commit()


def execute(query: str, params: tuple = ()) -> sqlite3.Cursor:
    """Execute a query and return the cursor."""
    conn = get_connection()
    return conn.execute(query, params)


def fetchone(query: str, params: tuple = ()) -> sqlite3.Row | None:
    """Execute and fetch one row."""
    return execute(query, params).fetchone()


def fetchall(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    """Execute and fetch all rows."""
    return execute(query, params).fetchall()


def execute_many(query: str, params_list: list[tuple]) -> None:
    """Execute a query with multiple parameter sets."""
    conn = get_connection()
    conn.executemany(query, params_list)
    conn.commit()
