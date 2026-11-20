"""Filesystem scans reconcile dashboard library inventory and missing items."""
from py_stremio.components.configs.config_file import DownloadConfig, QualitySettings, _save_config_json
from py_stremio.components.library.library_scanner import FolderType, ScannedFolder
from py_stremio.services.library_catalog import sync_catalog_from_folders
from py_stremio.storage.catalog import (
    get_missing_episodes,
    get_or_create_season,
    get_or_create_series,
    get_season_by_rel_path,
    upsert_files,
)
from py_stremio.storage.db import close_connection, init_db


def test_sync_reconciles_new_episode_files_and_removes_deleted_seasons(tmp_path, monkeypatch):
    root = tmp_path / "media"
    survivor_folder = root / "series" / "Survivor" / "s51"
    survivor_folder.mkdir(parents=True)
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings.ROOT_FOLDER", root)
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "library.sqlite"))
    monkeypatch.setattr("py_stremio.storage.compat._storage_backend", "sqlite")
    close_connection()
    init_db()

    old_series_id = get_or_create_series("House of the Dragon", "series/House of the Dragon", "tt11198330")
    old_season_id = get_or_create_season(
        old_series_id,
        3,
        "series/House of the Dragon/s03",
        {"episode_count": 8, "available_episodes": list(range(1, 9)), "enabled": True},
    )
    upsert_files("season", old_season_id, [{
        "rel_path": f"House.of.the.Dragon.S03E{episode:02d}.mkv",
        "episode": episode,
        "size": 100,
        "mtime_ns": episode,
        "is_part": False,
    } for episode in range(1, 6)])

    _save_config_json(
        survivor_folder / "download-config.json",
        DownloadConfig(
            type="series",
            title="Survivor",
            imdb_id="tt0239195",
            season=51,
            episode_count=9,
            available_episodes=list(range(1, 10)),
            quality=QualitySettings(),
        ),
    )
    for episode in range(1, 9):
        (survivor_folder / f"Survivor.S51E{episode:02d}.mkv").write_bytes(b"video")

    folder = ScannedFolder(survivor_folder, FolderType.SERIES, survivor_folder.parent, season_number=51)
    catalog_messages = []
    assert get_season_by_rel_path("series/Survivor/s51") is None
    sync_catalog_from_folders([folder], progress_callback=catalog_messages.append)

    survivor_id = get_or_create_series("Survivor", "series/Survivor", "tt0239195")
    survivor_season_id = get_or_create_season(survivor_id, 51, "series/Survivor/s51")
    missing = get_missing_episodes(survivor_season_id)
    assert [item.episode for item in missing] == [9]
    assert get_season_by_rel_path("series/House of the Dragon/s03") is None
    assert "Added to library: Survivor S51" in catalog_messages

    (survivor_folder / "Survivor.S51E01.mkv").unlink()
    sync_catalog_from_folders([folder], force=False)
    assert [item.episode for item in get_missing_episodes(survivor_season_id)] == [1, 9]
    close_connection()


def test_incomplete_scan_preserves_existing_catalog_entries(tmp_path, monkeypatch):
    root = tmp_path / "media"
    survivor_folder = root / "series" / "Survivor" / "s51"
    survivor_folder.mkdir(parents=True)
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings.ROOT_FOLDER", root)
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "partial-scan.sqlite"))
    monkeypatch.setattr("py_stremio.storage.compat._storage_backend", "sqlite")
    close_connection()
    init_db()

    series_id = get_or_create_series("Survivor", "series/Survivor", "tt0239195")
    for season in range(1, 7):
        get_or_create_season(
            series_id,
            season,
            f"series/Survivor/s{season:02d}",
            {"episode_count": 10, "available_episodes": list(range(1, 11)), "enabled": True},
        )
    _save_config_json(
        survivor_folder / "download-config.json",
        DownloadConfig(
            type="series",
            title="Survivor",
            imdb_id="tt0239195",
            season=51,
            episode_count=10,
            available_episodes=list(range(1, 11)),
            quality=QualitySettings(),
        ),
    )
    folder = ScannedFolder(survivor_folder, FolderType.SERIES, survivor_folder.parent, season_number=51)

    sync_catalog_from_folders([folder])

    assert get_season_by_rel_path("series/Survivor/s02") is not None
    assert get_season_by_rel_path("series/Survivor/s06") is not None
    close_connection()
