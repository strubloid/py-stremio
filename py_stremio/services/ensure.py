"""Catalog-backed freshness gate for SQLite installations."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from py_stremio.components.configs.app_settings import settings
from py_stremio.components.library.library_scanner import FolderType, ScannedFolder
from py_stremio.components.library.media_file import iter_video_files, scan_episode_files
from py_stremio.components.stremio.stremio_metadata import get_current_year_series_seasons
from py_stremio.services.metadata import MetadataService
from py_stremio.storage.catalog import (
    get_stale_movies,
    get_stale_seasons,
    get_or_create_season,
    set_season_metadata_due,
    update_movie_inventory_synced,
    update_season_inventory_synced,
    upsert_files,
)
from py_stremio.storage.db import fetchall, init_db, transaction


class EnsureFreshService:
    def __init__(self, metadata: MetadataService | None = None):
        self.metadata = metadata or MetadataService()

    def run(self, quiet: bool = True) -> list[ScannedFolder]:
        init_db()
        root = settings.ROOT_FOLDER
        self._sync_changed_inventory(root)
        folders = self._catalog_folders(root)
        by_rel_path = {str(folder.path.relative_to(root)): folder for folder in folders}
        stale_folders = []
        stale_season_rows = {row["id"]: row for row in get_stale_seasons()}
        for row in fetchall("SELECT * FROM seasons WHERE poster_url IS NULL"):
            stale_season_rows.setdefault(row["id"], dict(row))
        stale_movie_rows = {row["id"]: row for row in get_stale_movies()}
        for row in fetchall("SELECT * FROM movies WHERE poster_url IS NULL"):
            stale_movie_rows.setdefault(row["id"], dict(row))

        for kind, row in [("season", item) for item in stale_season_rows.values()]:
            folder = by_rel_path.get(row["rel_path"])
            if folder:
                stale_folders.append((kind, row["id"], folder))
        for row in stale_movie_rows.values():
            folder = by_rel_path.get(row["rel_path"])
            if folder:
                stale_folders.append(("movie", row["id"], folder))

        if stale_folders:
            self.metadata.run(
                folders=[item[2] for item in stale_folders],
                quiet=quiet,
                use_cache=False,
            )
            due_at = (datetime.now(timezone.utc) + timedelta(hours=settings.CONFIGS_CACHE_HOURS)).isoformat()
            with transaction() as conn:
                for kind, owner_id, _folder in stale_folders:
                    table = "seasons" if kind == "season" else "movies"
                    conn.execute(f"UPDATE {table} SET metadata_due_at = ? WHERE id = ?", (due_at, owner_id))

        new_folders = self._create_new_seasons(root, quiet)
        for folder in new_folders:
            rel_path = str(folder.path.relative_to(root))
            by_rel_path[rel_path] = folder
        if new_folders:
            self.metadata.run(folders=new_folders, quiet=quiet, use_cache=False)
            due_at = (datetime.now(timezone.utc) + timedelta(hours=settings.CONFIGS_CACHE_HOURS)).isoformat()
            with transaction() as conn:
                for folder in new_folders:
                    conn.execute(
                        "UPDATE seasons SET metadata_due_at = ? WHERE rel_path = ?",
                        (due_at, str(folder.path.relative_to(root))),
                    )
        return list(by_rel_path.values())

    def _sync_changed_inventory(self, root: Path) -> None:
        rows = [
            ("season", row) for row in fetchall("SELECT id, rel_path, sync_mtime_ns, available_episodes FROM seasons")
        ] + [("movie", row) for row in fetchall("SELECT id, rel_path, sync_mtime_ns FROM movies")]

        def stat_folder(item):
            kind, row = item
            path = root / row["rel_path"]
            try:
                return kind, row, path, path.stat().st_mtime_ns
            except OSError:
                return kind, row, path, None

        with ThreadPoolExecutor(max_workers=min(8, max(1, len(rows)))) as executor:
            for kind, row, path, mtime_ns in executor.map(stat_folder, rows):
                if mtime_ns is None or mtime_ns == row["sync_mtime_ns"]:
                    continue
                if kind == "season":
                    files = [
                        {
                            "rel_path": media.path.name,
                            "episode": media.episode,
                            "size": media.path.stat().st_size,
                            "mtime_ns": media.path.stat().st_mtime_ns,
                            "is_part": False,
                        }
                        for media in scan_episode_files(path)
                    ]
                    known = set(__import__("json").loads(row["available_episodes"] or "[]"))
                    if any(media["episode"] is not None and media["episode"] not in known for media in files):
                        set_season_metadata_due(row["id"])
                    update_season_inventory_synced(row["id"], mtime_ns)
                else:
                    files = [
                        {
                            "rel_path": media.name,
                            "episode": None,
                            "size": media.stat().st_size,
                            "mtime_ns": media.stat().st_mtime_ns,
                            "is_part": False,
                        }
                        for media in iter_video_files(path)
                    ]
                    update_movie_inventory_synced(row["id"], mtime_ns)
                upsert_files(kind, row["id"], files)

    def _catalog_folders(self, root: Path) -> list[ScannedFolder]:
        season_rows = fetchall(
            """SELECT seasons.rel_path, seasons.season FROM seasons
               JOIN series ON series.id = seasons.series_id WHERE seasons.enabled = 1"""
        )
        movie_rows = fetchall("SELECT rel_path FROM movies WHERE enabled = 1")
        folders = [
            ScannedFolder(
                path=root / row["rel_path"],
                folder_type=FolderType.SERIES,
                parent_folder=(root / row["rel_path"]).parent,
                season_number=row["season"],
            )
            for row in season_rows
        ]
        folders.extend(
            ScannedFolder(
                path=root / row["rel_path"],
                folder_type=FolderType.MOVIES,
                parent_folder=(root / row["rel_path"]).parent,
            )
            for row in movie_rows
        )
        return folders

    def _create_new_seasons(self, root: Path, quiet: bool) -> list[ScannedFolder]:
        year = datetime.now().year
        candidates = fetchall(
            "SELECT id, title, rel_path, latest_season FROM series WHERE latest_season < ? AND imdb_id IS NOT NULL",
            (year,),
        )
        created: list[ScannedFolder] = []
        for series in candidates:
            for season_info in get_current_year_series_seasons(series["title"], year):
                season = int(season_info.get("season") or 0)
                if season <= series["latest_season"] or not season_info.get("episode_count"):
                    continue
                series_path = root / series["rel_path"]
                season_path = series_path / f"s{season:02d}"
                if season_path.exists():
                    continue
                season_path.mkdir(parents=True, exist_ok=True)
                rel_path = str(season_path.relative_to(root))
                season_id = get_or_create_season(
                    series["id"],
                    season,
                    rel_path,
                    {"episode_count": season_info.get("episode_count"), "enabled": True},
                )
                with transaction() as conn:
                    conn.execute("UPDATE seasons SET metadata_due_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), season_id))
                    conn.execute(
                        "UPDATE series SET latest_season = MAX(latest_season, ?) WHERE id = ?",
                        (season, series["id"]),
                    )
                created.append(
                    ScannedFolder(
                        path=season_path,
                        folder_type=FolderType.SERIES,
                        parent_folder=series_path,
                        season_number=season,
                    )
                )
                if not quiet:
                    print(f"  + created {season_info.get('title') or series['title']} S{season:02d}")
        return created
