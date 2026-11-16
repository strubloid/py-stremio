"""Cached release-calendar data sourced from Cinemeta by IMDb ID."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from py_stremio.components.stremio.stremio_metadata import get_series_calendar_episodes
from py_stremio.storage.db import fetchall, init_db, transaction


CALENDAR_REFRESH_HOURS = 12


def refresh_calendar(force: bool = False) -> dict[str, int]:
    init_db()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=CALENDAR_REFRESH_HOURS)
    series = fetchall("SELECT id, imdb_id FROM series WHERE imdb_id IS NOT NULL")
    sync_rows = fetchall("SELECT series_id, refreshed_at FROM calendar_sync")
    last_refresh = {row["series_id"]: row["refreshed_at"] for row in sync_rows}
    stale = []
    for item in series:
        timestamp = last_refresh.get(item["id"])
        try:
            is_stale = timestamp is None or datetime.fromisoformat(timestamp) <= cutoff
        except ValueError:
            is_stale = True
        if force or is_stale:
            stale.append(item)
    if not stale:
        return {"checked": 0, "updated": 0, "failed": 0}

    with ThreadPoolExecutor(max_workers=min(8, len(stale))) as executor:
        results = list(executor.map(lambda row: get_series_calendar_episodes(row["imdb_id"]), stale))

    updated = 0
    failed = 0
    for item, episodes in zip(stale, results):
        refreshed_at = datetime.now(timezone.utc).isoformat()
        if episodes is None:
            failed += 1
            with transaction() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO calendar_sync (series_id, refreshed_at) VALUES (?, ?)",
                    (item["id"], refreshed_at),
                )
            continue
        with transaction() as conn:
            conn.execute("DELETE FROM calendar_episodes WHERE series_id=?", (item["id"],))
            conn.executemany(
                """INSERT INTO calendar_episodes
                   (series_id, season, episode, title, overview, release_at, thumbnail_url)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        item["id"], episode["season"], episode["episode"], episode["title"],
                        episode["overview"], episode["release_at"], episode["thumbnail_url"],
                    )
                    for episode in episodes
                ],
            )
            conn.execute(
                "INSERT OR REPLACE INTO calendar_sync (series_id, refreshed_at) VALUES (?, ?)",
                (item["id"], refreshed_at),
            )
        updated += 1
    return {"checked": len(stale), "updated": updated, "failed": failed}


def get_calendar_month(year: int, month: int) -> dict:
    init_db()
    month_key = f"{year:04d}-{month:02d}"
    events = fetchall(
        """SELECT calendar_episodes.*, series.title AS series_title, series.poster_url AS poster_url
           FROM calendar_episodes JOIN series ON series.id = calendar_episodes.series_id
           WHERE substr(calendar_episodes.release_at, 1, 7)=?
           ORDER BY calendar_episodes.release_at, series.title, calendar_episodes.season, calendar_episodes.episode""",
        (month_key,),
    )
    sync_rows = fetchall("SELECT series_id, refreshed_at FROM calendar_sync")
    sync_times = [row["refreshed_at"] for row in sync_rows]
    last_refreshed = max(sync_times) if sync_times else None
    series_count = fetchall("SELECT COUNT(*) AS count FROM series WHERE imdb_id IS NOT NULL")[0]["count"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CALENDAR_REFRESH_HOURS)
    needs_refresh = series_count > len(sync_rows) or any(datetime.fromisoformat(value) <= cutoff for value in sync_times)
    return {
        "year": year,
        "month": month,
        "events": [dict(event) for event in events],
        "last_refreshed": last_refreshed,
        "needs_refresh": needs_refresh,
    }
