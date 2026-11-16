"""Behavioral coverage for SQLite config, state, and freshness persistence."""
from py_stremio.components.configs.config_file import DownloadConfig, QualitySettings, load_config, save_config
from py_stremio.components.state.app_state import DownloadState, load_state, save_state
from py_stremio.storage import close_connection, init_db
from py_stremio.storage import compat
from py_stremio.storage.catalog import get_files, get_or_create_season, get_or_create_series
from py_stremio.storage.db import fetchone, transaction


def test_sqlite_backend_round_trips_config_and_download_state(tmp_path, monkeypatch):
    root = tmp_path / "library"
    season_folder = root / "series" / "Example Show" / "s01"
    season_folder.mkdir(parents=True)
    database = tmp_path / "catalog.sqlite"

    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings.ROOT_FOLDER", root)
    monkeypatch.setenv("PY_STREMIO_DB", str(database))
    monkeypatch.setattr(compat, "_storage_backend", "sqlite")
    close_connection()
    init_db()

    config = DownloadConfig(
        type="series",
        title="Example Show",
        imdb_id="tt1234567",
        season=1,
        episode_count=3,
        available_episodes=[1, 2, 3],
        quality=QualitySettings(preferred="720p", fallbacks=["480p"]),
    )
    config_path = season_folder / "download-config.json"
    save_config(config_path, config)

    state = DownloadState(folder_path=season_folder)
    state.mark_in_progress("episode_2", 512)
    state.mark_preflight_indeterminate("episode_3", "temporary rate limit")
    save_state(season_folder, state)

    loaded_config, _ = load_config(season_folder)
    loaded_state = load_state(season_folder)

    assert loaded_config.imdb_id == "tt1234567"
    assert loaded_config.available_episodes == [1, 2, 3]
    assert loaded_config.quality.preferred == "720p"
    assert loaded_state.in_progress["episode_2"]["part_bytes"] == 512
    assert loaded_state.preflight_indeterminate["episode_3"]["error"] == "temporary rate limit"
    assert not config_path.exists()
    close_connection()


def test_catalog_freshness_rescans_changed_folder_and_refreshes_new_episode(tmp_path, monkeypatch):
    root = tmp_path / "library"
    season_folder = root / "series" / "Example Show" / "s01"
    season_folder.mkdir(parents=True)
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings.ROOT_FOLDER", root)
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "freshness.sqlite"))
    monkeypatch.setattr(compat, "_storage_backend", "sqlite")
    close_connection()
    init_db()

    series_id = get_or_create_series("Example Show", "series/Example Show", "tt1234567")
    season_id = get_or_create_season(
        series_id,
        1,
        "series/Example Show/s01",
        {"episode_count": 1, "available_episodes": [1], "enabled": True},
    )
    with transaction() as conn:
        conn.execute("UPDATE seasons SET sync_mtime_ns = ? WHERE id = ?", (season_folder.stat().st_mtime_ns, season_id))

    (season_folder / "Example.Show.S01E02.mkv").write_bytes(b"video")
    metadata_calls = []

    class MetadataStub:
        def run(self, **kwargs):
            metadata_calls.extend(kwargs["folders"])

    import py_stremio.services.ensure as ensure

    monkeypatch.setattr(ensure, "get_current_year_series_seasons", lambda *args: [])
    folders = ensure.EnsureFreshService(MetadataStub()).run()

    assert [folder.path for folder in metadata_calls] == [season_folder]
    assert any(folder.path == season_folder for folder in folders)
    assert any(file["episode"] == 2 for file in get_files("season", season_id))
    close_connection()


def test_successful_json_migration_switches_default_backend_to_sqlite(tmp_path, monkeypatch):
    root = tmp_path / "library"
    season_folder = root / "series" / "Example Show" / "s01"
    season_folder.mkdir(parents=True)
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings.ROOT_FOLDER", root)
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings.STORAGE_BACKEND", "json")
    monkeypatch.delenv("STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "migrated.sqlite"))
    monkeypatch.setattr(compat, "_storage_backend", "json")
    close_connection()

    config = DownloadConfig(type="series", title="Example Show", season=1, episode_count=1)
    save_config(season_folder / "download-config.json", config)

    from py_stremio.storage.migration import migrate

    counts = migrate(root_folder=root)
    monkeypatch.setattr(compat, "_storage_backend", None)

    assert counts["seasons"] == 1
    assert compat.get_storage_backend() == "sqlite"
    assert (season_folder / "download-config.json").exists()
    close_connection()


def test_addon_health_counts_downloads_only_after_a_completed_download(tmp_path, monkeypatch):
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "addons.sqlite"))
    close_connection()
    init_db()
    from py_stremio.storage.repositories import AddonRepo

    url = "https://addon.example/manifest.json"
    AddonRepo.mark_tested_working(url)
    assert fetchone("SELECT downloads_completed FROM addons WHERE url = ?", (url,))["downloads_completed"] == 0

    AddonRepo.mark_working(url)

    assert fetchone("SELECT downloads_completed FROM addons WHERE url = ?", (url,))["downloads_completed"] == 1
    close_connection()


def test_metadata_persists_imdb_artwork_for_series_seasons_and_movies(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from py_stremio.services.metadata import _persist_artwork
    from py_stremio.storage.catalog import get_or_create_movie

    root = tmp_path / "library"
    season_folder = root / "series" / "Example Show" / "s01"
    movie_folder = root / "movies" / "Example Film"
    season_folder.mkdir(parents=True)
    movie_folder.mkdir(parents=True)
    monkeypatch.setattr("py_stremio.components.configs.app_settings.settings.ROOT_FOLDER", root)
    monkeypatch.setenv("PY_STREMIO_DB", str(tmp_path / "artwork.sqlite"))
    monkeypatch.setattr(compat, "_storage_backend", "sqlite")
    close_connection()
    init_db()

    series_id = get_or_create_series("Example Show", "series/Example Show", "tt7654321")
    season_id = get_or_create_season(series_id, 1, "series/Example Show/s01", {"episode_count": 1})
    movie_id = get_or_create_movie("Example Film", "movies/Example Film", "tt8765432")

    _persist_artwork(SimpleNamespace(path=season_folder), "season", {
        "poster_url": "https://images.example/series-poster.jpg",
        "background_url": "https://images.example/series-background.jpg",
        "season_poster_url": "https://images.example/season-poster.jpg",
    })
    _persist_artwork(SimpleNamespace(path=movie_folder), "movie", {
        "poster_url": "https://images.example/movie-poster.jpg",
    })

    assert fetchone("SELECT poster_url FROM series WHERE id=?", (series_id,))["poster_url"] == "https://images.example/series-poster.jpg"
    assert fetchone("SELECT poster_url FROM seasons WHERE id=?", (season_id,))["poster_url"] == "https://images.example/season-poster.jpg"
    assert fetchone("SELECT poster_url FROM movies WHERE id=?", (movie_id,))["poster_url"] == "https://images.example/movie-poster.jpg"
    close_connection()
